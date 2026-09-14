"""Freeze and append the ticket-6 owner quality series without cherry-picking."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api.catalogue import catalogue  # noqa: E402
from api.circulation import validate_circulation  # noqa: E402
from api.domain import resolve_design  # noqa: E402
from api.live_generation import ANCHOR_ID, frozen_generation_configuration  # noqa: E402
from api.models import DesignRequest, SolvedDesign  # noqa: E402

REFERENCE_SET_VERSION = "ticket-6-reference-candidates-v1"
RUN_INPUT_FIELDS = {"generationId", "referenceId", "outcome", "validOutcome", "configurationDigest", "timings", "usage", "design", "screenshot"}
RUN_RECORD_FIELDS = RUN_INPUT_FIELDS | {"index", "recordedAt", "freezeDigest", "screenshotSha256"}
JUDGMENT_INPUT_FIELDS = {"generationId", "ownerJudgment"}
JUDGMENT_RECORD_FIELDS = JUDGMENT_INPUT_FIELDS | {"recordedAt", "freezeDigest", "runIndex"}
RENDER_RECORD_FIELDS = {"generationId", "renderEvidenceValid"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files_digest(paths: list[Path]) -> dict[str, Any]:
    records = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)} for path in sorted(paths) if path.is_file()]
    return {"sha256": hashlib.sha256(canonical(records)).hexdigest(), "files": records}


def source_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, check=True, capture_output=True)
    return [ROOT / value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


def prepared_snapshot() -> dict[str, Any]:
    configuration = frozen_generation_configuration(catalogue)
    product_assets = files_digest(list((ROOT / "public" / "products").rglob("*")))
    source = files_digest(source_files())
    build = files_digest(list((ROOT / "dist").rglob("*")) if (ROOT / "dist").is_dir() else [])
    runtime_deliverables = {
        "publicDecoders": files_digest(list((ROOT / "public" / "decoders").rglob("*"))),
        "catalogueProviderManifests": files_digest(list((ROOT / "api" / "catalogue" / "providers" / "manifests").rglob("*"))),
    }
    content = {
        "version": "ticket-6-quality-freeze-v3", "createdAt": datetime.now(timezone.utc).isoformat(),
        "configuration": configuration, "source": source, "build": build, "productAssets": product_assets,
        "runtimeDeliverables": runtime_deliverables,
        "ownerImageApproval": "pending", "ownerScheduleApproval": "pending",
        "ownerBudgetAuthorization": "pending", "providerCapabilityProbe": "pending",
        "providerAccountingStart": "pending", "phoneGate": "waived",
    }
    content["configurationDigest"] = hashlib.sha256(canonical({
        "configuration": configuration, "sourceSha256": source["sha256"],
        "buildSha256": build["sha256"], "productAssetsSha256": product_assets["sha256"],
        "runtimeDeliverables": {
            name: value["sha256"] for name, value in runtime_deliverables.items()
        },
    })).hexdigest()
    return content


def write_new(path: Path, value: dict) -> None:
    path = path.expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise SystemExit("Ticket-6 quality evidence must stay outside the source checkout.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refusing to overwrite append-only evidence: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return value


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not all(isinstance(value, dict) for value in values):
        raise SystemExit(f"Append-only evidence contains a non-object record: {path}")
    return values


def _approved_record(path: Path) -> tuple[dict[str, Any], str]:
    value = _read_json(path)
    if value.get("approved") is not True or value.get("referenceSetVersion") != REFERENCE_SET_VERSION:
        raise SystemExit(f"Owner record is not an approval for {REFERENCE_SET_VERSION}: {path}")
    return value, sha(path)


def _verify_freeze(path: Path, *, require_current: bool) -> dict[str, Any]:
    value = _read_json(path)
    if value.get("preliminaryBuilderFreeze") is True or value.get("version") != "ticket-6-quality-freeze-v3":
        raise SystemExit("Only a final quality-freeze v3 can record or summarize a real series.")
    expected = value.get("freezeDigest")
    unsigned = dict(value)
    unsigned.pop("freezeDigest", None)
    if expected != hashlib.sha256(canonical(unsigned)).hexdigest():
        raise SystemExit("Frozen evidence digest does not match its contents.")
    required = ("ownerImageApproval", "ownerScheduleApproval", "ownerBudgetAuthorization", "providerCapabilityProbe", "providerAccountingStart")
    if not all(isinstance(value.get(key), dict) for key in required):
        raise SystemExit("Owner approvals, passed capability probe, and shared accounting start are required before recording evidence.")
    if require_current:
        current = prepared_snapshot()
        keys = ("configurationDigest", "configuration", "source", "build", "productAssets", "runtimeDeliverables")
        if any(current.get(key) != value.get(key) for key in keys):
            raise SystemExit(
                "Current source, build, Product bytes, runtime deliverables, or generation configuration drifted from the freeze."
            )
    return value


def _validate_claimed_design(raw_design: Any, reference_id: str, freeze: dict[str, Any]) -> None:
    try:
        design = SolvedDesign.model_validate(raw_design)
    except ValidationError as error:
        raise SystemExit("A claimed-valid run does not retain a complete valid solved Design.") from error
    if not design.intents or design.arrangementHistory is None or design.circulation is None:
        raise SystemExit("A claimed-valid run does not retain a complete valid solved Design.")

    configuration = freeze["configuration"]
    if design.room.model_dump(mode="json") != configuration["room"]:
        raise SystemExit("A claimed-valid Design does not use the frozen Room.")
    if [zone.model_dump(mode="json") for zone in design.zones] != configuration["zones"]:
        raise SystemExit("A claimed-valid Design does not use the frozen Zone offer.")

    intent_ids = [intent.id for intent in design.intents]
    placement_ids = [placement.instanceId for placement in design.placements]
    if len(set(intent_ids)) != len(intent_ids) or placement_ids != intent_ids:
        raise SystemExit("A claimed-valid Design has missing or misaligned Placement identities.")
    eligible_ids = set(configuration["catalogue"]["eligibleProductIdsByReference"].get(reference_id, ()))
    if not eligible_ids or any(product.id not in eligible_ids for product in design.products):
        raise SystemExit("A claimed-valid Design uses a Product outside the frozen reference eligibility.")
    frozen_products = {product["id"]: product for product in configuration["catalogue"]["products"]}
    if any(product.model_dump(mode="json") != frozen_products.get(product.id) for product in design.products):
        raise SystemExit("A claimed-valid Design does not retain the frozen Catalogue metadata.")
    anchors = [
        product
        for intent, product in zip(design.intents, design.products, strict=True)
        if intent.id == ANCHOR_ID and product.category == "bed"
    ]
    if len(anchors) != 1 or sum(product.category == "bed" for product in design.products) != 1:
        raise SystemExit("A claimed-valid Design does not retain the required bed anchor identity.")

    authoritative = resolve_design(catalogue, DesignRequest(
        room=design.room,
        intents=design.intents,
        maxCandidates=configuration["solver"]["maxCandidatesPerSolve"],
    ))
    if authoritative.status != "solved":
        raise SystemExit("A claimed-valid Design fails authoritative placement validation.")
    if (
        authoritative.products != design.products
        or authoritative.placements != design.placements
        or authoritative.fits != design.fits
        or authoritative.search != design.search
    ):
        raise SystemExit("A claimed-valid Design does not match authoritative placement validation.")
    circulation = validate_circulation(
        authoritative,
        configuration["solver"]["clearanceWidthM"],
        anchor_ids=frozenset({ANCHOR_ID}),
    )
    if circulation.status != "clear" or circulation != design.circulation:
        raise SystemExit("A claimed-valid Design fails authoritative circulation validation.")


def _validate_runs(runs: list[dict[str, Any]], freeze: dict[str, Any]) -> None:
    schedule = freeze["configuration"]["proposedTenRunSchedule"]
    seen: set[str] = set()
    if len(runs) > len(schedule):
        raise SystemExit("The series exceeds its frozen schedule.")
    for offset, run in enumerate(runs):
        if set(run) != RUN_RECORD_FIELDS:
            raise SystemExit("A prior run record does not match the frozen append-only contract.")
        if run["index"] != offset + 1 or run["referenceId"] != schedule[offset]:
            raise SystemExit("Prior run order does not match the frozen schedule.")
        if run["freezeDigest"] != freeze["freezeDigest"] or run["configurationDigest"] != freeze["configurationDigest"]:
            raise SystemExit("Prior series records mix freezes or configurations.")
        if run["generationId"] in seen:
            raise SystemExit("Prior series contains duplicate generation IDs.")
        seen.add(run["generationId"])
        if run["outcome"] not in {"solved", "failed"} or not isinstance(run["validOutcome"], bool):
            raise SystemExit("Prior run outcome is invalid.")
        if run["validOutcome"]:
            if run["outcome"] != "solved":
                raise SystemExit("Only a solved run retaining its complete Design can be valid.")
            _validate_claimed_design(run["design"], run["referenceId"], freeze)
        screenshot = Path(run["screenshot"]).expanduser().resolve()
        if not screenshot.is_file() or sha(screenshot) != run["screenshotSha256"]:
            raise SystemExit("A prior run screenshot is missing or has drifted.")


def _validate_judgments(judgments: list[dict[str, Any]], runs: list[dict[str, Any]], freeze: dict[str, Any]) -> None:
    by_id = {run["generationId"]: run for run in runs}
    seen: set[str] = set()
    for judgment in judgments:
        if set(judgment) != JUDGMENT_RECORD_FIELDS:
            raise SystemExit("A prior owner judgment does not match the append-only contract.")
        generation_id = judgment["generationId"]
        run = by_id.get(generation_id)
        if generation_id in seen or run is None:
            raise SystemExit("Owner judgments must be unique and refer to a recorded run.")
        seen.add(generation_id)
        if judgment["freezeDigest"] != freeze["freezeDigest"] or judgment["runIndex"] != run["index"]:
            raise SystemExit("Owner judgment is bound to the wrong freeze or run.")
        if type(judgment["ownerJudgment"]) is not bool:
            raise SystemExit("Owner judgment must be yes or no.")
        if judgment["ownerJudgment"] is True and (run["outcome"] != "solved" or run["validOutcome"] is not True):
            raise SystemExit("Owner yes is accepted only for a valid solved Design; owner no records failed or invalid outcomes.")


def prepare(args) -> None:
    write_new(args.output, prepared_snapshot())


def freeze(args) -> None:
    snapshot = prepared_snapshot()
    image_record, image_hash = _approved_record(args.image_approval)
    schedule_record, schedule_hash = _approved_record(args.schedule_approval)
    budget_record = _read_json(args.budget_authorization)
    if budget_record.get("approved") is not True or budget_record.get("capUsd") != 5.0:
        raise SystemExit("Owner budget authorization must bind the exact USD 5.00 total cap.")
    budget_path = Path(str(budget_record.get("accountingPath", ""))).expanduser().resolve()
    if budget_path == ROOT or ROOT in budget_path.parents:
        raise SystemExit("The authorized accounting path must remain outside the source checkout.")
    capability = _read_json(args.provider_capability)
    message = capability.get("message") if isinstance(capability.get("message"), dict) else {}
    reference = snapshot["configuration"]["references"][0]
    expected_production_binding = {
        "sourceSha256": snapshot["source"]["sha256"],
        "referenceId": reference["id"],
        "referenceSha256": reference["sha256"],
        "referenceBytes": reference["bytes"],
        "promptSha256": snapshot["configuration"]["promptContractSha256ByReference"][reference["id"]],
        "promptBytes": snapshot["configuration"]["promptContractBytesByReference"][reference["id"]],
        "schemaSha256": snapshot["configuration"]["providerOutputSchemaSha256"],
        "schemaBytes": snapshot["configuration"]["providerOutputSchemaBytes"],
        "model": "claude-opus-5",
        "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema", "maxTokens": 8192},
        "validation": "ProviderSelection plus shared Product/Room capabilities and graph policy",
    }
    if not (
        capability.get("status") == "passed"
        and capability.get("mode") == "production-message"
        and capability.get("workspaceHeaderConfigured") is True
        and capability.get("paidMessageAuthorizedByCommand") is True
        and capability.get("modelRequested") == "claude-opus-5"
        and capability.get("productionBinding") == expected_production_binding
        and message.get("modelReturned") == "claude-opus-5"
        and message.get("stopReason") == "end_turn"
        and message.get("schemaValid") is True
        and message.get("selectionRejection") is None
        and message.get("referenceId") == reference["id"]
        and message.get("settings") == {"thinking": "adaptive", "effort": "high", "format": "json_schema"}
    ):
        raise SystemExit("Provider production-schema evidence is not the exact current passed contract.")
    accounting = _read_json(args.provider_ledger)
    if accounting.get("capUsd") != 5.0 or not 0 <= accounting.get("committedUsd", -1) <= 5.0:
        raise SystemExit("Provider accounting start does not match the authorized USD 5.00 total cap.")
    if image_record.get("references") != snapshot["configuration"]["references"]:
        raise SystemExit("Owner image approval does not bind the exact image hashes, provenance, and private mappings.")
    if schedule_record.get("schedule") != snapshot["configuration"]["proposedTenRunSchedule"]:
        raise SystemExit("Owner-approved schedule does not match the predetermined ten-run schedule.")
    snapshot["ownerImageApproval"] = {"sha256": image_hash, "record": image_record}
    snapshot["ownerScheduleApproval"] = {"sha256": schedule_hash, "record": schedule_record}
    snapshot["ownerBudgetAuthorization"] = {"sha256": sha(args.budget_authorization), "record": budget_record}
    snapshot["providerCapabilityProbe"] = {"sha256": sha(args.provider_capability), "record": capability}
    snapshot["providerAccountingStart"] = {"sha256": sha(args.provider_ledger), "record": accounting}
    snapshot["frozenAt"] = datetime.now(timezone.utc).isoformat()
    snapshot["freezeDigest"] = hashlib.sha256(canonical(snapshot)).hexdigest()
    write_new(args.output, snapshot)


def preliminary_freeze(args) -> None:
    """Bind the builder candidate before the host-owned production probe/inspection."""
    snapshot = prepared_snapshot()
    image_record, image_hash = _approved_record(args.image_approval)
    schedule_record, schedule_hash = _approved_record(args.schedule_approval)
    budget_record = _read_json(args.budget_authorization)
    if budget_record.get("approved") is not True or budget_record.get("capUsd") != 5.0:
        raise SystemExit("Owner budget authorization must bind the exact USD 5.00 total cap.")
    accounting = _read_json(args.provider_ledger)
    if accounting.get("capUsd") != 5.0 or not 0 <= accounting.get("committedUsd", -1) <= 5.0:
        raise SystemExit("Provider accounting does not match the authorized USD 5.00 total cap.")
    if image_record.get("references") != snapshot["configuration"]["references"]:
        raise SystemExit("Owner image approval does not bind the exact image hashes, provenance, and private mappings.")
    if schedule_record.get("schedule") != snapshot["configuration"]["proposedTenRunSchedule"]:
        raise SystemExit("Owner-approved schedule does not match the predetermined ten-run schedule.")
    snapshot["version"] = "ticket-6-preliminary-builder-freeze-fix-2-v1"
    snapshot["preliminaryBuilderFreeze"] = True
    snapshot["ownerImageApproval"] = {"sha256": image_hash, "record": image_record}
    snapshot["ownerScheduleApproval"] = {"sha256": schedule_hash, "record": schedule_record}
    snapshot["ownerBudgetAuthorization"] = {"sha256": sha(args.budget_authorization), "record": budget_record}
    snapshot["providerCapabilityProbe"] = {"status": "pending-host-production-message"}
    snapshot["providerAccountingStart"] = {"sha256": sha(args.provider_ledger), "record": accounting}
    snapshot["frozenAt"] = datetime.now(timezone.utc).isoformat()
    snapshot["freezeDigest"] = hashlib.sha256(canonical(snapshot)).hexdigest()
    write_new(args.output, snapshot)


def append_run(args) -> None:
    freeze = _verify_freeze(args.freeze, require_current=True)
    run = _read_json(args.run)
    if set(run) != RUN_INPUT_FIELDS or run["configurationDigest"] != freeze["configurationDigest"]:
        raise SystemExit("Run fields or configuration digest do not match the freeze.")
    if run["outcome"] not in {"solved", "failed"} or not isinstance(run["validOutcome"], bool):
        raise SystemExit("Run outcome or validity is invalid.")
    if run["validOutcome"]:
        if run["outcome"] != "solved":
            raise SystemExit("Only a solved run retaining its complete Design can be valid.")
        _validate_claimed_design(run["design"], run["referenceId"], freeze)
    screenshot = Path(run["screenshot"]).expanduser().resolve()
    if not screenshot.is_file():
        raise SystemExit("Every run, including a failure, needs a screenshot.")
    series = args.series.expanduser().resolve()
    series.parent.mkdir(parents=True, exist_ok=True)
    prior = _read_lines(series)
    _validate_runs(prior, freeze)
    schedule = freeze["configuration"]["proposedTenRunSchedule"]
    if len(prior) >= len(schedule):
        raise SystemExit("The frozen ten-run series is already complete.")
    if any(item["generationId"] == run["generationId"] for item in prior):
        raise SystemExit("Generation IDs must be unique within the series.")
    if run["referenceId"] != schedule[len(prior)]:
        raise SystemExit("Run reference does not match the next frozen schedule entry.")
    record = {"index": len(prior) + 1, "recordedAt": datetime.now(timezone.utc).isoformat(), "freezeDigest": freeze["freezeDigest"], "screenshotSha256": sha(screenshot), **run}
    with series.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def append_judgment(args) -> None:
    freeze = _verify_freeze(args.freeze, require_current=True)
    runs = _read_lines(args.series)
    _validate_runs(runs, freeze)
    prior = _read_lines(args.judgments)
    _validate_judgments(prior, runs, freeze)
    value = _read_json(args.judgment)
    if set(value) != JUDGMENT_INPUT_FIELDS or type(value.get("ownerJudgment")) is not bool:
        raise SystemExit("Owner judgment fields do not match the append-only contract.")
    run = next((item for item in runs if item["generationId"] == value["generationId"]), None)
    if run is None:
        raise SystemExit("Owner judgment must refer to a recorded outcome.")
    if value["ownerJudgment"] is True and (run["outcome"] != "solved" or run["validOutcome"] is not True):
        raise SystemExit("Owner yes is accepted only for a valid solved Design; owner no records failed or invalid outcomes.")
    if any(item["generationId"] == value["generationId"] for item in prior):
        raise SystemExit("Owner judgment for this generation is already recorded.")
    record = {"recordedAt": datetime.now(timezone.utc).isoformat(), "freezeDigest": freeze["freezeDigest"], "runIndex": run["index"], **value}
    args.judgments.parent.mkdir(parents=True, exist_ok=True)
    with args.judgments.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def summarize(args) -> None:
    freeze = _verify_freeze(args.freeze, require_current=True)
    runs = _read_lines(args.series)
    judgments = _read_lines(args.judgments)
    _validate_runs(runs, freeze)
    _validate_judgments(judgments, runs, freeze)
    judged = {item["generationId"]: item["ownerJudgment"] for item in judgments}
    valid = [run for run in runs if run["outcome"] == "solved" and run["validOutcome"] is True]
    invalid_successes = sum(run["outcome"] == "solved" and run["validOutcome"] is False for run in runs)
    owner_yes = sum(judged.get(run["generationId"]) is True for run in valid)
    owner_no = sum(value is False for value in judged.values())
    owner_pending = len(freeze["configuration"]["proposedTenRunSchedule"]) - len(judged)
    complete = len(runs) == 10 and owner_pending == 0
    result = {"runsRecorded": len(runs), "complete": complete, "solvedValid": len(valid), "failedOrInvalid": len(runs) - len(valid), "invalidSuccesses": invalid_successes, "ownerYes": owner_yes, "ownerNo": owner_no, "ownerPending": owner_pending, "qualityGatePassed": complete and invalid_successes == 0 and owner_yes >= 7}
    print(json.dumps(result, indent=2, sort_keys=True))


def technical_summary(args) -> None:
    """Report the validity-first gate separately from deferred owner aesthetics."""
    freeze = _verify_freeze(args.freeze, require_current=True)
    runs = _read_lines(args.series)
    _validate_runs(runs, freeze)
    render_by_id: dict[str, bool] = {}
    if args.render_evidence is not None:
        raw = _read_json(args.render_evidence)
        if set(raw) != {"freezeDigest", "runs"} or raw["freezeDigest"] != freeze["freezeDigest"]:
            raise SystemExit("Rendered evidence is not bound to the exact technical-trial freeze.")
        records = raw["runs"]
        if not isinstance(records, list):
            raise SystemExit("Rendered evidence runs must be an array.")
        for record in records:
            if not isinstance(record, dict) or set(record) != RENDER_RECORD_FIELDS:
                raise SystemExit("Rendered evidence does not match the bounded contract.")
            generation_id = record["generationId"]
            valid = record["renderEvidenceValid"]
            if not isinstance(generation_id, str) or type(valid) is not bool or generation_id in render_by_id:
                raise SystemExit("Rendered evidence generation ids must be unique and validity must be boolean.")
            render_by_id[generation_id] = valid
        if set(render_by_id) != {run["generationId"] for run in runs}:
            raise SystemExit("Rendered evidence must cover exactly every recorded technical-trial run.")

    valid = [run for run in runs if run["outcome"] == "solved" and run["validOutcome"] is True]
    invalid_successes = sum(run["outcome"] == "solved" and run["validOutcome"] is False for run in runs)
    rendered_valid = sum(
        render_by_id.get(run["generationId"]) is True
        and run["outcome"] == "solved"
        and run["validOutcome"] is True
        for run in runs
    )
    complete = len(runs) == len(freeze["configuration"]["proposedTenRunSchedule"]) == 10
    server_passed = complete and len(valid) == 10 and invalid_successes == 0
    render_passed = complete and len(render_by_id) == 10 and rendered_valid == 10
    result = {
        "evaluationMode": "validity-first",
        "runsRecorded": len(runs),
        "complete": complete,
        "serverValidDesigns": len(valid),
        "failedOrInvalid": len(runs) - len(valid),
        "invalidSuccesses": invalid_successes,
        "serverDesignValidityPassed": server_passed,
        "renderEvidenceProvided": args.render_evidence is not None,
        "renderedValidDesigns": rendered_valid,
        "renderedEvidencePassed": render_passed,
        "technicalValidityPassed": server_passed and render_passed,
        "aestheticOwnerGate": "deferred-separate-7-of-10-judgment",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)
    prepare_p = sub.add_parser("prepare"); prepare_p.add_argument("--output", type=Path, required=True); prepare_p.set_defaults(function=prepare)
    freeze_p = sub.add_parser("freeze"); freeze_p.add_argument("--image-approval", type=Path, required=True); freeze_p.add_argument("--schedule-approval", type=Path, required=True); freeze_p.add_argument("--budget-authorization", type=Path, required=True); freeze_p.add_argument("--provider-capability", type=Path, required=True); freeze_p.add_argument("--provider-ledger", type=Path, required=True); freeze_p.add_argument("--output", type=Path, required=True); freeze_p.set_defaults(function=freeze)
    preliminary_p = sub.add_parser("preliminary-freeze"); preliminary_p.add_argument("--image-approval", type=Path, required=True); preliminary_p.add_argument("--schedule-approval", type=Path, required=True); preliminary_p.add_argument("--budget-authorization", type=Path, required=True); preliminary_p.add_argument("--provider-ledger", type=Path, required=True); preliminary_p.add_argument("--output", type=Path, required=True); preliminary_p.set_defaults(function=preliminary_freeze)
    run_p = sub.add_parser("append-run"); run_p.add_argument("--freeze", type=Path, required=True); run_p.add_argument("--run", type=Path, required=True); run_p.add_argument("--series", type=Path, required=True); run_p.set_defaults(function=append_run)
    judgment_p = sub.add_parser("append-judgment"); judgment_p.add_argument("--freeze", type=Path, required=True); judgment_p.add_argument("--series", type=Path, required=True); judgment_p.add_argument("--judgment", type=Path, required=True); judgment_p.add_argument("--judgments", type=Path, required=True); judgment_p.set_defaults(function=append_judgment)
    summary_p = sub.add_parser("summary"); summary_p.add_argument("--freeze", type=Path, required=True); summary_p.add_argument("--series", type=Path, required=True); summary_p.add_argument("--judgments", type=Path, required=True); summary_p.set_defaults(function=summarize)
    technical_p = sub.add_parser("technical-summary"); technical_p.add_argument("--freeze", type=Path, required=True); technical_p.add_argument("--series", type=Path, required=True); technical_p.add_argument("--render-evidence", type=Path); technical_p.set_defaults(function=technical_summary)
    args = parser.parse_args(); args.function(args); return 0


if __name__ == "__main__":
    raise SystemExit(main())
