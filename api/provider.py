"""Bounded Anthropic transport and persistent local spend reservations."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import base64
import binascii
from math import isfinite
import os
from pathlib import Path
from queue import Queue
import threading
from time import monotonic
from typing import Any, Iterator, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MODEL_ID = "claude-opus-5"
ANTHROPIC_API = "https://api.anthropic.com"
MAX_OUTPUT_TOKENS = 8192
MAX_COUNTED_INPUT_TOKENS = 80_000
MAX_RESPONSE_BYTES = 1_048_576
MAX_PROMPT_TEXT_BYTES = 32_768
MAX_PROVIDER_SCHEMA_BYTES = 32_768
MAX_IMAGE_BYTES = 400_000
MAX_IMAGE_EDGE_PX = 1_800
MAX_IMAGE_SHORT_EDGE_PX = 1_200
MAX_IMAGE_VISUAL_TOKENS = 2_795
MAX_SERIALIZED_REQUEST_BYTES = 786_432
CONSERVATIVE_INPUT_TOKEN_RESERVATION = 80_000
CONNECT_TIMEOUT_SECONDS = 10.0
CALL_DEADLINE_SECONDS = 90.0
OVERALL_DEADLINE_SECONDS = 300.0
INPUT_USD_PER_MILLION = 5.0
OUTPUT_USD_PER_MILLION = 25.0
AUTHORIZED_TOTAL_CAP_USD = 5.0
AccountingMode = Literal["capped", "uncapped"]


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read SOF dimensions without decoding or changing the immutable JPEG."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ProviderCallError("schema-error", "Provider image is not a valid bounded JPEG.")
    offset = 2
    start_of_frame = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            break
        if marker in start_of_frame and length >= 7:
            height = int.from_bytes(data[offset + 3:offset + 5], "big")
            width = int.from_bytes(data[offset + 5:offset + 7], "big")
            if width > 0 and height > 0:
                return width, height
            break
        offset += length
    raise ProviderCallError("schema-error", "Provider image dimensions could not be verified.")

ProviderErrorCode = Literal[
    "configuration-error",
    "budget-error",
    "transport-error",
    "timeout",
    "rate-limit",
    "provider-error",
    "schema-error",
]


class ProviderCallError(RuntimeError):
    def __init__(
        self,
        code: ProviderErrorCode,
        detail: str,
        *,
        attempted: bool = False,
        usage: Any = None,
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.attempted = attempted
        self.usage = usage


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    inputTokens: int = Field(ge=0)
    outputTokens: int = Field(ge=0)
    costUsd: float = Field(ge=0, allow_inf_nan=False)


@dataclass(frozen=True)
class ProviderReply:
    payload: dict[str, Any]
    model: str
    stop_reason: str
    usage: ProviderUsage | None
    latency_ms: int


@dataclass(frozen=True)
class ProviderSettings:
    api_key: str
    workspace_id: str | None
    spend_cap_usd: float | None
    accounting_path: Path
    accounting_mode: AccountingMode = "capped"

    @classmethod
    def from_environment(cls) -> "ProviderSettings":
        if os.environ.get("FURNITUREOS_LIVE_GENERATION_ENABLED") != "1":
            raise ProviderCallError("configuration-error", "Live generation is disabled by server configuration.")
        if os.environ.get("VERCEL"):
            raise ProviderCallError(
                "configuration-error",
                "Live generation remains disabled on serverless hosts because the approved local ledger cannot provide persistent accounting there.",
            )

        direct_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        direct_workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip() or None
        key = direct_key
        workspace_id = direct_workspace_id
        credential_file = os.environ.get("ANTHROPIC_CREDENTIAL_FILE", "").strip()
        if credential_file:
            if direct_key or direct_workspace_id:
                raise ProviderCallError(
                    "configuration-error",
                    "External credential files must not be combined with direct Anthropic key or workspace overrides.",
                )
            path = Path(credential_file).expanduser().resolve()
            repository = Path(__file__).resolve().parents[1]
            if path.suffix != ".local" or path == repository or repository in path.parents:
                raise ProviderCallError(
                    "configuration-error",
                    "The configured credential file must be an external .local file.",
                )
            try:
                values = _read_local_values(path)
            except OSError as error:
                raise ProviderCallError("configuration-error", "The configured credential file is unavailable.") from error
            key = values.get("ANTHROPIC_API_KEY", "").strip()
            workspace_id = values.get("ANTHROPIC_WORKSPACE_ID", "").strip() or None

        if not key:
            raise ProviderCallError("configuration-error", "Server credentials are not configured.")
        if not workspace_id:
            raise ProviderCallError("configuration-error", "The authorized account workspace ID is not configured.")
        mode_raw = os.environ.get("FURNITUREOS_GENERATION_SPEND_MODE", "").strip() or "capped"
        if mode_raw not in {"capped", "uncapped"}:
            raise ProviderCallError("configuration-error", "Generation accounting mode must be explicitly capped or uncapped.")
        accounting_mode: AccountingMode = mode_raw  # type: ignore[assignment]
        cap_raw = os.environ.get("FURNITUREOS_GENERATION_SPEND_CAP_USD", "").strip()
        accounting_raw = os.environ.get("FURNITUREOS_GENERATION_ACCOUNTING_PATH", "").strip()
        if accounting_mode == "uncapped":
            if cap_raw:
                raise ProviderCallError("configuration-error", "Uncapped accounting must not include a numeric cap.")
            cap: float | None = None
        else:
            try:
                cap = float(cap_raw)
            except ValueError as error:
                raise ProviderCallError("configuration-error", "An authorized positive session spend cap is required.") from error
            if not (isfinite(cap) and 0 < cap <= AUTHORIZED_TOTAL_CAP_USD):
                raise ProviderCallError("configuration-error", "The session spend cap must not exceed the owner-authorized USD 5.00 total.")
        if not accounting_raw:
            raise ProviderCallError("configuration-error", "A persistent accounting path is required.")
        accounting_path = Path(accounting_raw).expanduser().resolve()
        repository = Path(__file__).resolve().parents[1]
        if accounting_path == repository or repository in accounting_path.parents:
            raise ProviderCallError("configuration-error", "Provider accounting must stay outside the repository.")
        return cls(key, workspace_id, cap, accounting_path, accounting_mode)


def provider_configuration_available() -> bool:
    """Use the execution parser so direct and external-file config agree."""
    try:
        ProviderSettings.from_environment()
    except ProviderCallError:
        return False
    return True


def _read_local_values(path: Path) -> dict[str, str]:
    allowed = {"ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID"}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() in allowed:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_THREAD_LOCK = threading.Lock()


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class BudgetLedger:
    """Single-host persistent accounting with serialized reservations.

    Capped mode enforces a hard local cap for callers sharing this file.
    Explicit uncapped mode keeps the same reservation/settlement history but
    deliberately omits only that aggregate comparison. Neither mode is a
    provider-account limit. Unknown usage retains the full reservation.
    """

    def __init__(
        self,
        path: Path,
        cap_usd: float | None,
        *,
        accounting_mode: AccountingMode = "capped",
    ):
        if accounting_mode == "capped":
            if cap_usd is None or not isfinite(cap_usd) or cap_usd <= 0:
                raise ProviderCallError("budget-error", "Capped accounting requires a finite positive cap.")
        elif accounting_mode == "uncapped":
            if cap_usd is not None:
                raise ProviderCallError("budget-error", "Uncapped accounting must not serialize a numeric cap.")
        else:
            raise ProviderCallError("budget-error", "Provider accounting mode is invalid.")
        self.path = path
        self.cap_usd = cap_usd
        self.accounting_mode = accounting_mode
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def _new_state(self) -> dict[str, Any]:
        return {
            "version": 2,
            "accountingMode": self.accounting_mode,
            "capUsd": self.cap_usd,
            "committedUsd": 0.0,
            "reservations": [],
        }

    def _validated_state(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ProviderCallError("budget-error", "Provider accounting state is invalid.")
        version = state.get("version")
        if version == 1:
            old_cap = state.get("capUsd")
            if not isinstance(old_cap, (int, float)) or isinstance(old_cap, bool) or not isfinite(old_cap) or old_cap <= 0:
                raise ProviderCallError("budget-error", "Provider accounting state is invalid.")
            if self.accounting_mode == "capped" and abs(float(old_cap) - float(self.cap_usd)) > 1e-9:
                raise ProviderCallError("budget-error", "Provider accounting cap or mode does not match this session.")
            state = dict(state)
            state["version"] = 2
            state["accountingMode"] = self.accounting_mode
            state["capUsd"] = self.cap_usd
            state["migratedFrom"] = {"version": 1, "capUsd": float(old_cap)}
        elif version != 2:
            raise ProviderCallError("budget-error", "Provider accounting version is invalid.")

        if state.get("accountingMode") != self.accounting_mode:
            raise ProviderCallError("budget-error", "Provider accounting mode does not match this session.")
        stored_cap = state.get("capUsd")
        if self.accounting_mode == "uncapped":
            if stored_cap is not None:
                raise ProviderCallError("budget-error", "Provider accounting cap is invalid for uncapped mode.")
        elif (
            not isinstance(stored_cap, (int, float))
            or isinstance(stored_cap, bool)
            or not isfinite(stored_cap)
            or abs(float(stored_cap) - float(self.cap_usd)) > 1e-9
        ):
            raise ProviderCallError("budget-error", "Provider accounting cap or mode does not match this session.")
        committed = state.get("committedUsd")
        reservations = state.get("reservations")
        if (
            not isinstance(committed, (int, float))
            or isinstance(committed, bool)
            or not isfinite(committed)
            or committed < 0
            or not isinstance(reservations, list)
        ):
            raise ProviderCallError("budget-error", "Provider accounting state is invalid.")
        for reservation in reservations:
            maximum = reservation.get("maximumUsd") if isinstance(reservation, dict) else None
            status = reservation.get("status") if isinstance(reservation, dict) else None
            if (
                not isinstance(reservation, dict)
                or not isinstance(reservation.get("id"), str)
                or not reservation["id"]
                or status not in {"reserved-unknown", "settled", "settled-over-reservation"}
                or not isinstance(maximum, (int, float))
                or isinstance(maximum, bool)
                or not isfinite(maximum)
                or maximum < 0
            ):
                raise ProviderCallError("budget-error", "Provider accounting reservation history is invalid.")
            actual = reservation.get("actualUsd")
            if actual is not None and (
                not isinstance(actual, (int, float))
                or isinstance(actual, bool)
                or not isfinite(actual)
                or actual < 0
            ):
                raise ProviderCallError("budget-error", "Provider accounting reservation history is invalid.")
            if status != "reserved-unknown" and actual is None:
                raise ProviderCallError("budget-error", "Provider accounting reservation history is invalid.")
        return state

    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        with _THREAD_LOCK, _exclusive_file_lock(self.lock_path):
            if self.path.exists():
                try:
                    state = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise ProviderCallError("budget-error", "Provider accounting state is unreadable.") from error
            else:
                state = self._new_state()
            state = self._validated_state(state)
            try:
                yield state
            finally:
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                os.replace(temporary, self.path)

    def reserve(self, counted_input_tokens: int) -> tuple[str, float]:
        if not 0 <= counted_input_tokens <= MAX_COUNTED_INPUT_TOKENS:
            raise ProviderCallError("budget-error", "Counted prompt tokens exceed the configured production bound.")
        # count_tokens is useful validation, not a billing guarantee. The fixed
        # 80k ceiling is independently derived from 32 KiB prompt + 32 KiB
        # schema (a tokenizer cannot emit more tokens than UTF-8 bytes), 2,795
        # verified visual patches, and over 11k tokens of framing/headroom.
        input_tokens = CONSERVATIVE_INPUT_TOKEN_RESERVATION
        amount = (
            input_tokens * INPUT_USD_PER_MILLION / 1_000_000
            + MAX_OUTPUT_TOKENS * OUTPUT_USD_PER_MILLION / 1_000_000
        )
        reservation_id = str(uuid4())
        with self._locked() as state:
            if any(item.get("status") == "settled-over-reservation" for item in state["reservations"]):
                raise ProviderCallError("budget-error", "Provider accounting is closed after usage exceeded a reservation.")
            committed = float(state["committedUsd"])
            if (
                self.accounting_mode == "capped"
                and committed + amount > float(self.cap_usd) + 1e-12
            ):
                raise ProviderCallError("budget-error", "The authorized local generation spend cap has no room for this call.")
            state["committedUsd"] = committed + amount
            state["reservations"].append({
                "id": reservation_id,
                "status": "reserved-unknown",
                "maximumUsd": amount,
                "countedInputTokens": counted_input_tokens,
                "inputTokensBound": input_tokens,
                "outputTokensBound": MAX_OUTPUT_TOKENS,
            })
        return reservation_id, amount

    def settle(self, reservation_id: str, usage: ProviderUsage) -> None:
        with self._locked() as state:
            reservation = next((item for item in state["reservations"] if item["id"] == reservation_id), None)
            if reservation is None or reservation["status"] != "reserved-unknown":
                raise ProviderCallError("budget-error", "Provider accounting reservation is missing or already settled.")
            maximum = float(reservation["maximumUsd"])
            state["committedUsd"] = float(state["committedUsd"]) - maximum + usage.costUsd
            reservation.update({
                "status": "settled-over-reservation" if usage.costUsd > maximum + 1e-12 else "settled",
                "actualUsd": usage.costUsd,
                "inputTokens": usage.inputTokens,
                "outputTokens": usage.outputTokens,
            })
            if usage.costUsd > maximum + 1e-12:
                # Actual usage is persisted first. The now-overdrawn ledger
                # rejects later reservations even if this call is reported as
                # an accounting failure to its caller.
                raise ProviderCallError("budget-error", "Reported provider usage exceeded its reservation.", attempted=True)


class AnthropicProvider:
    def __init__(self, settings: ProviderSettings, *, client: httpx.Client | None = None):
        self.settings = settings
        self.ledger = BudgetLedger(
            settings.accounting_path,
            settings.spend_cap_usd,
            accounting_mode=settings.accounting_mode,
        )
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {
            "x-api-key": self.settings.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.settings.workspace_id:
            headers["anthropic-workspace-id"] = self.settings.workspace_id
        return headers

    def _bounded_request(
        self,
        method: Literal["GET", "POST"],
        url: str,
        *,
        deadline_at: float,
        attempted: bool,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, bytes]:
        """Stream one response under byte and genuine wall-clock bounds."""
        call_deadline = min(deadline_at, monotonic() + CALL_DEADLINE_SECONDS)
        if call_deadline <= monotonic():
            raise ProviderCallError("timeout", "The provider request deadline elapsed.", attempted=attempted)
        result: Queue[tuple[str, Any]] = Queue(maxsize=1)
        client_holder: list[httpx.Client] = []

        def perform() -> None:
            owned = self._client is None
            timeout = httpx.Timeout(
                max(0.001, call_deadline - monotonic()),
                connect=min(CONNECT_TIMEOUT_SECONDS, max(0.001, call_deadline - monotonic())),
            )
            client = self._client or httpx.Client(timeout=timeout, follow_redirects=False)
            client_holder.append(client)
            try:
                with client.stream(method, url, headers=self._headers(), json=body) as response:
                    if response.history:
                        raise ProviderCallError("provider-error", "Provider redirects are not accepted.", attempted=attempted)
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                        raise ProviderCallError("provider-error", "Provider response exceeded the 1 MiB limit.", attempted=attempted)
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if monotonic() > call_deadline:
                            raise ProviderCallError("timeout", "The provider request exceeded its wall-clock deadline.", attempted=attempted)
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE_BYTES:
                            raise ProviderCallError("provider-error", "Provider response exceeded the 1 MiB limit.", attempted=attempted)
                    result.put(("ok", (response.status_code, bytes(content))))
            except BaseException as error:  # transferred to the request-owning thread
                result.put(("error", error))
            finally:
                if owned:
                    client.close()

        worker = threading.Thread(target=perform, name="anthropic-bounded-request", daemon=True)
        worker.start()
        worker.join(max(0, call_deadline - monotonic()))
        if worker.is_alive():
            if client_holder:
                try:
                    client_holder[0].close()
                except Exception:
                    pass
            raise ProviderCallError("timeout", "The provider request exceeded its wall-clock deadline.", attempted=attempted)
        outcome, value = result.get_nowait()
        if outcome == "error":
            if isinstance(value, ProviderCallError):
                raise value
            if isinstance(value, httpx.TimeoutException):
                raise ProviderCallError("timeout", "The provider request timed out.", attempted=attempted) from value
            if isinstance(value, httpx.HTTPError):
                raise ProviderCallError("transport-error", "The provider transport failed.", attempted=attempted) from value
            raise ProviderCallError("transport-error", "The provider request failed.", attempted=attempted) from value
        return value

    @staticmethod
    def _response_json(body: bytes, *, attempted: bool) -> dict[str, Any]:
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderCallError("schema-error", "Provider returned invalid JSON.", attempted=attempted) from error
        if not isinstance(value, dict):
            raise ProviderCallError("schema-error", "Provider returned an invalid response shape.", attempted=attempted)
        return value

    @staticmethod
    def _usage_from_payload(payload: dict[str, Any] | None) -> ProviderUsage | None:
        if payload is None:
            return None
        raw_usage = payload.get("usage")
        if not isinstance(raw_usage, dict):
            return None
        input_used = raw_usage.get("input_tokens")
        output_used = raw_usage.get("output_tokens")
        if type(input_used) is not int or type(output_used) is not int:
            return None
        try:
            return ProviderUsage(
                inputTokens=input_used,
                outputTokens=output_used,
                costUsd=(input_used * INPUT_USD_PER_MILLION + output_used * OUTPUT_USD_PER_MILLION) / 1_000_000,
            )
        except ValidationError:
            return None

    @staticmethod
    def _raise_status(status_code: int, *, attempted: bool) -> None:
        if 200 <= status_code < 300:
            return
        if status_code == 429:
            code: ProviderErrorCode = "rate-limit"
        elif status_code in (401, 403):
            code = "configuration-error"
        else:
            code = "provider-error"
        raise ProviderCallError(code, f"Provider request failed with HTTP {status_code}.", attempted=attempted)

    def retrieve_model(self, deadline_at: float) -> dict[str, Any]:
        """Exact-model metadata for the separately authorized account probe."""
        remaining = deadline_at - monotonic()
        if remaining <= 0:
            raise ProviderCallError("timeout", "The provider probe deadline elapsed.")
        status, body = self._bounded_request(
            "GET", f"{ANTHROPIC_API}/v1/models/{MODEL_ID}", deadline_at=deadline_at, attempted=False,
        )
        self._raise_status(status, attempted=False)
        payload = self._response_json(body, attempted=False)
        if payload.get("id") != MODEL_ID:
            raise ProviderCallError("schema-error", "Provider metadata did not identify the exact requested model.")
        return payload

    def generate(
        self,
        *,
        prompt_text: str,
        image_media_type: Literal["image/jpeg"],
        image_base64: str,
        output_schema: dict[str, Any],
        deadline_at: float,
    ) -> ProviderReply:
        prompt_bytes = len(prompt_text.encode("utf-8"))
        try:
            image = base64.b64decode(image_base64, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ProviderCallError("schema-error", "Provider image base64 is invalid.") from error
        image_bytes = len(image)
        width, height = _jpeg_dimensions(image)
        visual_tokens = ((width + 27) // 28) * ((height + 27) // 28)
        schema_bytes = len(json.dumps(output_schema, separators=(",", ":")).encode("utf-8"))
        if (
            prompt_bytes > MAX_PROMPT_TEXT_BYTES
            or image_bytes > MAX_IMAGE_BYTES
            or schema_bytes > MAX_PROVIDER_SCHEMA_BYTES
            or max(width, height) > MAX_IMAGE_EDGE_PX
            or min(width, height) > MAX_IMAGE_SHORT_EDGE_PX
            or visual_tokens > MAX_IMAGE_VISUAL_TOKENS
        ):
            raise ProviderCallError("schema-error", "Provider prompt exceeds configured text, image, or schema bounds.")
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_media_type, "data": image_base64}},
                {"type": "text", "text": prompt_text},
            ],
        }]
        body = {
            "model": MODEL_ID,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": "high",
                "format": {"type": "json_schema", "schema": output_schema},
            },
            "messages": messages,
        }
        serialized_request_bytes = len(json.dumps(body, separators=(",", ":")).encode("utf-8"))
        if serialized_request_bytes > MAX_SERIALIZED_REQUEST_BYTES:
            raise ProviderCallError("schema-error", "Serialized provider request exceeds its production byte bound.")
        remaining = deadline_at - monotonic()
        if remaining <= 0:
            raise ProviderCallError("timeout", "The overall generation deadline elapsed.")
        # count_tokens accepts the full input/schema configuration but rejects
        # the Messages-only output limit as an extra field.
        count_body = {key: value for key, value in body.items() if key != "max_tokens"}
        count_status, count_content = self._bounded_request(
            "POST",
            f"{ANTHROPIC_API}/v1/messages/count_tokens",
            deadline_at=deadline_at,
            attempted=False,
            body=count_body,
        )
        self._raise_status(count_status, attempted=False)
        count_payload = self._response_json(count_content, attempted=False)
        input_tokens = count_payload.get("input_tokens")
        if not isinstance(input_tokens, int):
            raise ProviderCallError("schema-error", "Provider token count was missing or invalid.")
        reservation_id, _maximum = self.ledger.reserve(input_tokens)

        started = monotonic()
        remaining = deadline_at - started
        if remaining <= 0:
            raise ProviderCallError("timeout", "The overall generation deadline elapsed before the reserved call.")
        status, content = self._bounded_request(
            "POST",
            f"{ANTHROPIC_API}/v1/messages",
            deadline_at=deadline_at,
            attempted=True,
            body=body,
        )
        latency_ms = round((monotonic() - started) * 1000)
        payload: dict[str, Any] | None = None
        try:
            payload = self._response_json(content, attempted=True)
        except ProviderCallError:
            # A malformed error body must not replace the bounded, sanitized
            # HTTP status failure or release its conservative reservation.
            if 200 <= status < 300:
                raise
        usage = self._usage_from_payload(payload)
        if usage is not None:
            try:
                self.ledger.settle(reservation_id, usage)
            except ProviderCallError as error:
                error.usage = usage
                raise
        try:
            self._raise_status(status, attempted=True)
        except ProviderCallError as error:
            error.usage = usage
            raise
        assert payload is not None
        if payload.get("model") != MODEL_ID:
            raise ProviderCallError("schema-error", "Provider returned a model other than the exact requested model.", attempted=True, usage=usage)
        if payload.get("stop_reason") != "end_turn":
            raise ProviderCallError("schema-error", "Provider did not finish with the documented successful stop reason.", attempted=True, usage=usage)
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderCallError("schema-error", "Provider content blocks were missing.", attempted=True, usage=usage)
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type") == "text")
        try:
            selection_payload = json.loads(text)
        except (TypeError, json.JSONDecodeError) as error:
            raise ProviderCallError("schema-error", "Provider structured output was not valid JSON.", attempted=True, usage=usage) from error
        if not isinstance(selection_payload, dict):
            raise ProviderCallError("schema-error", "Provider structured output had the wrong shape.", attempted=True, usage=usage)
        return ProviderReply(
            payload=selection_payload,
            model=str(payload.get("model") or MODEL_ID),
            stop_reason=str(payload.get("stop_reason") or "unknown"),
            usage=usage,
            latency_ms=latency_ms,
        )
