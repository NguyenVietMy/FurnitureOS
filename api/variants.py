"""Sequential solved Variants and a backpressured, cancellable NDJSON boundary."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from math import degrees
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Annotated, Callable, Literal
from uuid import uuid4

from fastapi.responses import StreamingResponse
from pydantic import Field, RootModel

from .generation_context import Conversation, work_scope
from .live_generation import StrictModel, LiveGenerationSuccess, LiveGenerationFailure, UsageSummary, generate_for_room, _usage_summary
from .models import RoomShell
from .provider import ProviderCallError

WORK_SECONDS = 270.0
REQUEST_SECONDS = 300.0
MAX_EVENT_BYTES = 524_288
Label = Literal["A", "B", "C"]
STREAM_RESPONSES = {200: {"content": {"application/x-ndjson": {
    "schema": {"$ref": "#/components/schemas/VariantStreamEvent"},
}}}}


class ShellEvent(StrictModel):
    type: Literal["shell"] = "shell"
    generationId: str
    room: RoomShell


class ProgressEvent(StrictModel):
    type: Literal["progress"] = "progress"
    generationId: str
    variant: Label
    stage: Literal["selecting", "duplicate-retry"]


class VariantEvent(StrictModel):
    type: Literal["variant"] = "variant"
    generationId: str
    variant: Label
    signature: str
    result: LiveGenerationSuccess


class CompleteEvent(StrictModel):
    type: Literal["complete"] = "complete"
    generationId: str
    status: Literal["complete", "partial", "failed"]
    available: tuple[Label, ...]
    reason: Literal["complete", "duplicate-exhausted", "generation-failed", "timeout", "cancelled"]
    providerCalls: int = Field(ge=0, le=15)
    usage: UsageSummary


class ErrorEvent(StrictModel):
    type: Literal["error"] = "error"
    generationId: str
    code: str
    detail: str
    invalidated: bool = False
    failure: LiveGenerationFailure | None = None


class VariantStreamEvent(RootModel[Annotated[ShellEvent | ProgressEvent | VariantEvent | CompleteEvent | ErrorEvent, Field(discriminator="type")]]):
    pass


def solved_signature(design) -> str:
    def quantize(value, scale):
        return int((Decimal(str(value)) * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    rows = sorted((p.productId, *(quantize(v, 100) for v in p.position),
                   quantize(degrees(p.yaw) % 360, 1) % 360) for p in design.placements)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class BatchStopped(Exception):
    def __init__(self, reason):
        self.reason = reason


@dataclass
class BatchControl:
    cancelled: Event = field(default_factory=Event)
    clock: Callable[[], float] = monotonic
    deadline_at: float | None = None
    request_deadline_at: float | None = None
    authority: Callable[[], None] = lambda: None
    generation_id: str = field(default_factory=lambda: str(uuid4()))
    conversation: Conversation | None = None
    available: list[Label] = field(default_factory=list)

    def __post_init__(self):
        started = self.clock()
        if self.deadline_at is None:
            self.deadline_at = started + WORK_SECONDS
        if self.request_deadline_at is None:
            self.request_deadline_at = started + REQUEST_SECONDS

    def check_request(self):
        if self.cancelled.is_set():
            raise BatchStopped("cancelled")
        if self.clock() >= self.request_deadline_at:
            raise BatchStopped("timeout")

    def check(self):
        self.check_request()
        if self.deadline_at is not None and self.clock() >= self.deadline_at:
            raise BatchStopped("timeout")


class DeadlineStreamingResponse(StreamingResponse):
    """Also bound authority awaits and stalled ASGI sends, not just paid work."""

    def __init__(self, *args, control: BatchControl, **kwargs):
        self.control = control
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(max(0, self.control.request_deadline_at - self.control.clock())):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            # Headers may already be sent. A truncated response is interruption,
            # never implicit success; ready Variants stay usable in the client.
            pass
        finally:
            self.control.cancelled.set()


def variant_events(source, request, room, sessions, *, provider=None, control=None,
                   binding=None, generation_id=None):
    control = control or BatchControl()
    if control.deadline_at is None:
        control.deadline_at = control.clock() + WORK_SECONDS
    generation_id = generation_id or control.generation_id
    control.generation_id = generation_id
    conversation = Conversation()
    control.conversation = conversation
    available = []
    control.available = available
    signatures = set()
    reason = "complete"
    try:
        control.check()
        control.authority()
        yield ShellEvent(generationId=generation_id, room=room)
        with work_scope(control.check):
            for label in ("A", "B", "C"):
                for candidate in range(1 if label == "A" else 2):
                    control.check()
                    control.authority()
                    conversation.candidate, conversation.duplicate = label, candidate > 0
                    yield ProgressEvent(generationId=generation_id, variant=label,
                                        stage="duplicate-retry" if candidate else "selecting")
                    control.check()
                    result = generate_for_room(source, request, room=room, private_room=binding is not None,
                                               provider=provider, conversation=conversation,
                                               deadline_at=control.deadline_at, clock=control.clock)
                    control.check()
                    control.authority()
                    if result.status == "failed":
                        yield ErrorEvent(generationId=generation_id, code=result.code, detail=result.detail, failure=result)
                        reason = "generation-failed"
                        break
                    signature = solved_signature(result.design)
                    duplicate = signature in signatures
                    conversation.solved(result.design, signature, duplicate)
                    if duplicate:
                        if candidate == 1:
                            reason = "duplicate-exhausted"
                        continue
                    control.check()
                    control.authority()
                    design = sessions.register(result.design, request.roomType, binding=binding)
                    if design.swap is None or design.swap.status != "available":
                        reason = "generation-failed"
                        yield ErrorEvent(generationId=generation_id, code="mutation-session-unavailable",
                                         detail="A mutation session could not be created. Available Variants are retained; retry generation explicitly.")
                        break
                    session_id = design.swap.sessionId
                    delivered = False
                    try:
                        control.check()
                        control.authority()
                        yield VariantEvent(generationId=generation_id, variant=label, signature=signature,
                                           result=result.model_copy(update={"design": design}))
                        delivered = True
                    finally:
                        if not delivered and session_id:
                            sessions.revoke(session_id)
                    signatures.add(signature)
                    available.append(label)
                    break
                if reason != "complete":
                    break
    except BatchStopped as error:
        reason = error.reason
    except ProviderCallError:
        reason = "generation-failed"
        yield ErrorEvent(generationId=generation_id, code="context-limit", detail="The bounded generation context could not continue.")
    # Capture errors are handled at the stream boundary, which clears private output.
    if not control.cancelled.is_set():
        control.authority()
        yield CompleteEvent(generationId=generation_id, status="complete" if len(available) == 3 else "partial" if available else "failed",
                            available=tuple(available), reason=reason, providerCalls=conversation.calls,
                            usage=_usage_summary(conversation.usages))


def stream_response(request, factory, control, *, lease_context=None, invalidate=None):
    """Worker owns its lease until it can no longer publish. Each event is acknowledged.

    Disconnect never waits for blocking provider I/O on the event loop. It sets
    the shared guard, so an in-flight call may finish but cannot solve/publish.
    """
    queue = Queue(maxsize=1)
    acknowledged = Event()
    emitted = Event()
    done = Event()

    def publish(event):
        control.check_request()
        control.check() if event.type not in ("complete", "error") else None
        if control.cancelled.is_set():
            raise BatchStopped("cancelled")
        encoded = event.model_dump_json() + "\n"
        if len(encoded.encode()) > MAX_EVENT_BYTES:
            raise ProviderCallError("schema-error", "Variant event exceeded its byte bound.")
        acknowledged.clear()
        emitted.clear()
        queue.put((event, encoded))
        while not acknowledged.wait(.05):
            if control.cancelled.is_set():
                raise BatchStopped("cancelled")
        if not emitted.is_set():
            raise BatchStopped("cancelled")

    def run():
        events = None
        try:
            with lease_context() if lease_context else nullcontext():
                events = factory()
                for event in events:
                    publish(event)
        except BatchStopped:
            pass
        except Exception:
            if invalidate:
                invalidate()
            if not control.cancelled.is_set():
                # No private geometry, provider raw text, credentials or exception detail.
                event = ErrorEvent(generationId=getattr(control, "generation_id", "unavailable"), code="generation-unavailable",
                                   detail="Generation access changed or the stream could not continue. Generate again explicitly.", invalidated=invalidate is not None)
                try:
                    publish(event)
                    retained = () if invalidate else tuple(control.available)
                    publish(CompleteEvent(generationId=event.generationId, status="partial" if retained else "failed", available=retained,
                                          reason="generation-failed", providerCalls=control.conversation.calls if control.conversation else 0,
                                          usage=_usage_summary(control.conversation.usages) if control.conversation else UsageSummary(known=False)))
                except BatchStopped:
                    pass
        finally:
            if events:
                events.close()
            done.set()

    async def body():
        worker = Thread(target=run, name="variant-stream", daemon=True)
        worker.start()
        delivered_labels = []
        invalidation_sent = False
        try:
            while not done.is_set() or not queue.empty():
                try:
                    control.check_request()
                except BatchStopped:
                    return
                if await request.is_disconnected():
                    return
                try:
                    event, encoded = queue.get_nowait()
                except Empty:
                    await asyncio.sleep(.02)
                    continue
                # Errors may contain derived private Zones; completion retains earlier
                # output. Both need the same final authority as a furnished Variant.
                # Only a geometry-free invalidation and its empty completion may
                # cross the boundary after that authority has been lost.
                sanitized_invalidation = event.type == "error" and event.invalidated and event.failure is None
                empty_invalidation_end = invalidation_sent and event.type == "complete" and not event.available and event.status == "failed"
                if not sanitized_invalidation and not empty_invalidation_end:
                    try:
                        await asyncio.wait_for(asyncio.to_thread(control.authority),
                                               timeout=max(0, control.request_deadline_at - control.clock()))
                        control.check_request()
                        if event.type not in ("error", "complete"):
                            control.check()
                    except BatchStopped as stopped:
                        if stopped.reason == "timeout":
                            yield CompleteEvent(generationId=event.generationId, status="partial" if delivered_labels else "failed",
                                available=tuple(delivered_labels), reason="timeout", providerCalls=control.conversation.calls if control.conversation else 0,
                                usage=_usage_summary(control.conversation.usages) if control.conversation else UsageSummary(known=False)).model_dump_json() + "\n"
                        return
                    except TimeoutError:
                        return
                    except Exception:
                        if invalidate:
                            invalidate()
                        yield ErrorEvent(generationId=event.generationId, code="generation-unavailable", detail="Generation access expired.", invalidated=invalidate is not None).model_dump_json() + "\n"
                        yield CompleteEvent(generationId=event.generationId, status="failed", available=(), reason="generation-failed",
                            providerCalls=control.conversation.calls if control.conversation else 0,
                            usage=_usage_summary(control.conversation.usages) if control.conversation else UsageSummary(known=False)).model_dump_json() + "\n"
                        return
                yield encoded
                if sanitized_invalidation:
                    invalidation_sent = True
                if event.type == "variant":
                    delivered_labels.append(event.variant)
                emitted.set()
                acknowledged.set()
        finally:
            control.cancelled.set()
            acknowledged.set()

    return DeadlineStreamingResponse(body(), control=control, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"})
