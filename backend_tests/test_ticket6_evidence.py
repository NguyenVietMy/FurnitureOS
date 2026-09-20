from __future__ import annotations

from argparse import Namespace
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from api.catalogue import catalogue
from api.live_generation import LiveGenerationRequest, frozen_generation_configuration, generate_live_bedroom
from api.provider import MODEL_ID, ProviderReply, ProviderUsage
from scripts import ticket6_evidence as evidence
from scripts import provider_probe


def _snapshot() -> dict:
    value = {
        "version": evidence.QUALITY_FREEZE_VERSION,
        "createdAt": "controlled",
        "configuration": frozen_generation_configuration(catalogue),
        "source": {"sha256": "source", "files": []},
        "build": {"sha256": "build", "files": []},
        "productAssets": {"sha256": "products", "files": []},
        "runtimeDeliverables": {
            "publicDecoders": {"sha256": "decoders", "files": []},
            "catalogueProviderManifests": {"sha256": "manifests", "files": []},
        },
        "ownerImageApproval": {"record": "controlled"},
        "ownerScheduleApproval": {"record": "controlled"},
        "ownerBudgetAuthorization": {"sha256": evidence.FIX5_AUTHORIZATION_SHA256, "record": _fix5_authorization()},
        "providerCapabilityProbe": {"record": "controlled"},
        "providerAccountingStart": _wrapper(_migrated_ledger(), "current-ledger"),
        "providerAccountingPath": str(evidence.FIX5_LEDGER_PATH),
        "phoneGate": "waived",
        "configurationDigest": "configuration",
        "frozenAt": "controlled",
    }
    preliminary = deepcopy(value)
    preliminary.update(
        version=evidence.PRELIMINARY_FREEZE_VERSION,
        preliminaryBuilderFreeze=True,
        providerCapabilityProbe={"status": "pending-host-production-message"},
        providerAccountingHistorical=_wrapper(_historical_ledger(), evidence.FIX4_HISTORICAL_LEDGER_SHA256),
        providerAccountingStart=_wrapper(_baseline_ledger(), evidence.FIX5_MIGRATION_BASELINE_SHA256),
        providerAccountingMigration=_preliminary_migration_metadata(),
    )
    preliminary.pop("providerAccountingBaseline", None)
    preliminary.pop("freezeDigest", None)
    preliminary["freezeDigest"] = hashlib.sha256(evidence.canonical(preliminary)).hexdigest()
    value["providerAccountingBaseline"] = preliminary
    value["providerAccountingMigration"] = _final_migration_metadata()
    value["freezeDigest"] = hashlib.sha256(evidence.canonical(value)).hexdigest()
    return value


def _fix4_authorization() -> dict:
    return {
        "approvedPlanSha256": evidence.FIX4_PLAN_SHA256,
        "builderSession": evidence.FIX4_BUILDER_SESSION,
        "requestedLocalAccountingMode": "uncapped; retain usage and unresolved charges",
        "providerBillingChangesAuthorized": False,
        "maximumFixRoundsTotal": 4,
        "maximumInspectionRoundsTotal": 5,
        "credentialWorkspaceId": evidence.FIX4_WORKSPACE_ID,
    }


def _fix5_authorization() -> dict:
    return {
        "ownerReply": "just go over the limit all u want",
        "interpretation": "Numerical source-fix and independent-review round limits lifted for the existing ticket-6 recovery work. Independent review retained.",
        "maximumFixRoundsTotal": None,
        "maximumInspectionRoundsTotal": None,
        "nextFixRound": 5,
        "nextInspectionRound": 6,
        "builderSession": evidence.FIX4_BUILDER_SESSION,
        "priorAuthorization": str(evidence.FIX4_AUTHORIZATION_PATH),
        "workOrderSha256": evidence.FIX5_WORK_ORDER_SHA256,
        "ledgerBeforeSha256": evidence.FIX5_MIGRATION_BASELINE_SHA256,
        "ledgerPath": str(evidence.FIX5_LEDGER_PATH),
        "providerBillingChangesAuthorized": False,
        "publicationAuthorized": False,
        "phoneGate": "waived",
    }


def _historical_ledger() -> dict:
    return {
        "version": 1,
        "capUsd": 10.0,
        "committedUsd": 0.6048,
        "reservations": [{"id": "unknown-hold", "status": "reserved-unknown", "maximumUsd": 0.6048}],
    }


def _baseline_ledger() -> dict:
    value = deepcopy(_historical_ledger())
    value["committedUsd"] = 0.7048
    value["reservations"].append({"id": "settled-diagnostic", "status": "settled", "maximumUsd": 0.6048, "actualUsd": 0.1})
    return value


def _migrated_ledger() -> dict:
    value = deepcopy(_baseline_ledger())
    value.update(version=2, accountingMode="uncapped", capUsd=None, migratedFrom={"version": 1, "capUsd": 10.0})
    return value


def _preliminary_migration_metadata() -> dict:
    return {
        "status": "pending-host-post-inspection",
        "targetMode": "uncapped",
        "targetVersion": 2,
        "authorizedHistoricalLedgerSha256": evidence.FIX4_HISTORICAL_LEDGER_SHA256,
        "postDiagnosticBaselineLedgerSha256": evidence.FIX5_MIGRATION_BASELINE_SHA256,
        "preservedHistoricalPrefixRows": len(_historical_ledger()["reservations"]),
        "baselineRows": len(_baseline_ledger()["reservations"]),
    }


def _final_migration_metadata() -> dict:
    return {
        "status": "completed-lineage-verified",
        "mode": "uncapped",
        "version": 2,
        "migratedFrom": {"version": 1, "capUsd": float(_baseline_ledger()["capUsd"])},
        "historicalPrefixRows": len(_historical_ledger()["reservations"]),
        "postDiagnosticBaselineRows": len(_baseline_ledger()["reservations"]),
        "baselineLedgerSha256": evidence.FIX5_MIGRATION_BASELINE_SHA256,
    }


def _wrapper(record: dict, file_sha256: str) -> dict:
    return {"sha256": file_sha256, "recordDigest": hashlib.sha256(evidence.canonical(record)).hexdigest(), "record": record}


@pytest.fixture(autouse=True)
def controlled_lineage_constants(monkeypatch, tmp_path: Path) -> None:
    prior = tmp_path / "owner-authorization-fix-4.json"
    _write(prior, _fix4_authorization())
    monkeypatch.setattr(evidence, "FIX4_AUTHORIZATION_PATH", prior)
    monkeypatch.setattr(evidence, "FIX4_AUTHORIZATION_SHA256", evidence.sha(prior))
    monkeypatch.setattr(evidence, "FIX5_AUTHORIZATION_SHA256", "controlled-authorization")
    monkeypatch.setattr(evidence, "FIX4_HISTORICAL_LEDGER_SHA256", "controlled-historical")
    monkeypatch.setattr(evidence, "FIX4_HISTORICAL_LEDGER_CANONICAL_SHA256", hashlib.sha256(evidence.canonical(_historical_ledger())).hexdigest())
    monkeypatch.setattr(evidence, "FIX5_MIGRATION_BASELINE_SHA256", "controlled-baseline")
    monkeypatch.setattr(evidence, "FIX5_MIGRATION_BASELINE_CANONICAL_SHA256", hashlib.sha256(evidence.canonical(_baseline_ledger())).hexdigest())
    ledger = tmp_path / "provider-live-budget.json"
    _write(ledger, _migrated_ledger())
    monkeypatch.setattr(evidence, "FIX5_LEDGER_PATH", ledger)


def _uncapped_ledger() -> dict:
    return _migrated_ledger()


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _run(
    freeze: dict,
    screenshot: Path,
    index: int,
    *,
    outcome: str = "failed",
    valid: bool = False,
    design: dict | None = None,
) -> dict:
    value = {
        "generationId": f"generation-{index}",
        "referenceId": freeze["configuration"]["proposedTenRunSchedule"][index - 1],
        "outcome": outcome, "validOutcome": valid,
        "configurationDigest": freeze["configurationDigest"], "timings": {}, "usage": {},
        "design": deepcopy(design) if outcome == "solved" else None, "screenshot": str(screenshot),
    }
    return {
        "index": index, "recordedAt": "controlled", "freezeDigest": freeze["freezeDigest"],
        "screenshotSha256": evidence.sha(screenshot), **value,
    }


class _SolvedProvider:
    def __init__(self, product_id: str):
        self.product_id = product_id

    def generate(self, **_kwargs):
        return ProviderReply(
            payload={"intents": [{
                "id": "anchor-bed",
                "kind": "against",
                "productId": self.product_id,
                "wallId": "wall-north",
                "face": "back",
            }]},
            model=MODEL_ID,
            stop_reason="end_turn",
            usage=ProviderUsage(inputTokens=100, outputTokens=20, costUsd=0.001),
            latency_ms=1,
        )


class _SequenceProvider:
    def __init__(self, payloads: list[dict]):
        self.payloads = iter(payloads)

    def generate(self, **_kwargs):
        return ProviderReply(
            payload=next(self.payloads),
            model=MODEL_ID,
            stop_reason="end_turn",
            usage=ProviderUsage(inputTokens=100, outputTokens=20, costUsd=0.001),
            latency_ms=1,
        )


@pytest.fixture(scope="module")
def valid_designs() -> dict[str, dict]:
    beds = {
        "ref-01": "bed-prudence-tufted-queen-natural",
        "ref-02": "bed-alkove-hayes-double-wild-oak",
        "ref-03": "bed-prudence-tufted-queen-natural",
        "ref-04": "bed-rivet-jonathan-queen-walnut",
        "ref-06": "bed-prudence-tufted-queen-natural",
    }
    designs: dict[str, dict] = {}
    for reference_id, product_id in beds.items():
        result = generate_live_bedroom(
            catalogue,
            LiveGenerationRequest(roomType="bedroom", referenceId=reference_id),
            provider=_SolvedProvider(product_id),
            generation_id_factory=lambda: "controlled",
        )
        assert result.status == "solved"
        designs[reference_id] = result.design.model_dump(mode="json")
    return designs


@pytest.fixture(scope="module")
def valid_bed_rug_design() -> dict:
    bed = "bed-prudence-tufted-queen-natural"
    rug = "rug-ravenna-prospect-moroccan"
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=_SequenceProvider([
            {"intents": [
                {"id": "anchor-bed", "kind": "against", "productId": bed, "wallId": "wall-north", "face": "back"},
                {"id": "area-rug", "kind": "in_zone", "productId": rug, "zoneId": "zone-418b5e9c7f7d"},
            ]},
            {"intents": [
                {"id": "anchor-bed", "kind": "against", "productId": bed, "wallId": "wall-north", "face": "back"},
                {"id": "area-rug", "kind": "in_zone", "productId": rug, "zoneId": "zone-f1237d317578"},
            ]},
        ]),
        generation_id_factory=lambda: "controlled-bed-rug",
    )
    assert result.status == "solved"
    return result.design.model_dump(mode="json")


def _series_runs(freeze: dict, screenshot: Path, valid_designs: dict[str, dict]) -> list[dict]:
    runs = []
    for index, reference_id in enumerate(freeze["configuration"]["proposedTenRunSchedule"], start=1):
        runs.append(_run(
            freeze,
            screenshot,
            index,
            outcome="solved",
            valid=True,
            design=valid_designs[reference_id],
        ))
    return runs


def _current_snapshot(freeze: dict) -> dict:
    current = dict(freeze)
    current.pop("freezeDigest")
    return current


def _production_binding(snapshot: dict) -> dict:
    reference = snapshot["configuration"]["references"][0]
    return {
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
        "validation": "ProviderSelection plus bed-plus-optional-rug-v1 scope and shared Product/Room capabilities and graph policy",
        "placementGuidance": "authoritative-bed-only-v1 plus bounded bed/rug complete-Design repair feedback",
    }


def _freeze_lineage_inputs(monkeypatch, tmp_path: Path, current_ledger: dict) -> tuple[Namespace, dict, Path]:
    ledger_path = tmp_path / "provider-live-budget.json"
    monkeypatch.setattr(evidence, "FIX5_LEDGER_PATH", ledger_path)
    historical_path = tmp_path / "historical.json"
    baseline_path = tmp_path / "baseline.json"
    _write(historical_path, _historical_ledger())
    _write(baseline_path, _baseline_ledger())
    monkeypatch.setattr(evidence, "FIX4_HISTORICAL_LEDGER_SHA256", evidence.sha(historical_path))
    monkeypatch.setattr(evidence, "FIX4_HISTORICAL_LEDGER_CANONICAL_SHA256", hashlib.sha256(evidence.canonical(_historical_ledger())).hexdigest())
    monkeypatch.setattr(evidence, "FIX5_MIGRATION_BASELINE_SHA256", evidence.sha(baseline_path))
    monkeypatch.setattr(evidence, "FIX5_MIGRATION_BASELINE_CANONICAL_SHA256", hashlib.sha256(evidence.canonical(_baseline_ledger())).hexdigest())

    authorization_record = _fix5_authorization()
    authorization = tmp_path / "authorization.json"
    _write(authorization, authorization_record)
    monkeypatch.setattr(evidence, "FIX5_AUTHORIZATION_SHA256", evidence.sha(authorization))

    prepared = _snapshot()
    prepared.pop("freezeDigest")
    for key in (
        "ownerImageApproval", "ownerScheduleApproval", "ownerBudgetAuthorization",
        "providerCapabilityProbe", "providerAccountingStart",
    ):
        prepared[key] = "pending"
    prepared.pop("providerAccountingPath", None)
    prepared.pop("providerAccountingBaseline", None)
    prepared.pop("providerAccountingMigration", None)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: deepcopy(prepared))

    image = tmp_path / "image.json"; schedule = tmp_path / "schedule.json"
    capability = tmp_path / "capability.json"; migration_baseline = tmp_path / "preliminary.json"
    _write(image, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "references": prepared["configuration"]["references"]})
    _write(schedule, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "schedule": prepared["configuration"]["proposedTenRunSchedule"]})
    _write(capability, {
        "status": "passed", "mode": "production-message", "workspaceHeaderConfigured": True,
        "workspaceId": evidence.FIX4_WORKSPACE_ID, "accountingMode": "uncapped",
        "paidMessageAuthorizedByCommand": True, "modelRequested": "claude-opus-5",
        "productionBinding": _production_binding(prepared),
        "message": {"modelReturned": "claude-opus-5", "stopReason": "end_turn", "schemaValid": True, "selectionRejection": None, "referenceId": "ref-01", "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema"}},
    })
    preliminary = deepcopy(prepared)
    preliminary.update(
        version=evidence.PRELIMINARY_FREEZE_VERSION,
        preliminaryBuilderFreeze=True,
        ownerImageApproval={"sha256": evidence.sha(image), "record": json.loads(image.read_text())},
        ownerScheduleApproval={"sha256": evidence.sha(schedule), "record": json.loads(schedule.read_text())},
        ownerBudgetAuthorization={"sha256": evidence.sha(authorization), "record": authorization_record},
        providerCapabilityProbe={"status": "pending-host-production-message"},
        providerAccountingPath=str(ledger_path.resolve()),
        providerAccountingHistorical=_wrapper(_historical_ledger(), evidence.sha(historical_path)),
        providerAccountingStart=_wrapper(_baseline_ledger(), evidence.sha(baseline_path)),
        providerAccountingMigration=_preliminary_migration_metadata(),
    )
    preliminary["freezeDigest"] = hashlib.sha256(evidence.canonical(preliminary)).hexdigest()
    _write(migration_baseline, preliminary)
    _write(ledger_path, current_ledger)
    return Namespace(
        image_approval=image, schedule_approval=schedule, budget_authorization=authorization,
        provider_capability=capability, provider_ledger=ledger_path,
        migration_baseline=migration_baseline, output=tmp_path / "final.json",
    ), prepared, ledger_path


def test_append_recomputes_current_configuration_and_rejects_source_drift(monkeypatch, tmp_path: Path) -> None:
    freeze = _snapshot()
    freeze_path = tmp_path / "freeze.json"
    _write(freeze_path, freeze)
    drifted = {**freeze, "configurationDigest": "drifted"}
    drifted.pop("freezeDigest")
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: drifted)
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    run = {key: value for key, value in _run(freeze, screenshot, 1).items() if key in evidence.RUN_INPUT_FIELDS}
    run_path = tmp_path / "run.json"; _write(run_path, run)
    with pytest.raises(SystemExit, match="drifted"):
        evidence.append_run(Namespace(freeze=freeze_path, run=run_path, series=tmp_path / "series.jsonl"))


def test_append_rejects_prior_records_from_a_mixed_freeze(monkeypatch, tmp_path: Path) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    current = dict(freeze); current.pop("freezeDigest")
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: current)
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    prior = _run(freeze, screenshot, 1); prior["freezeDigest"] = "other-freeze"
    series = tmp_path / "series.jsonl"; _write(series, prior)
    run = {key: value for key, value in _run(freeze, screenshot, 2).items() if key in evidence.RUN_INPUT_FIELDS}
    run_path = tmp_path / "run.json"; _write(run_path, run)
    with pytest.raises(SystemExit, match="mix"):
        evidence.append_run(Namespace(freeze=freeze_path, run=run_path, series=series))


def test_exact_image_approval_content_is_required(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot(); snapshot.pop("freezeDigest")
    snapshot["ownerImageApproval"] = "pending"; snapshot["ownerScheduleApproval"] = "pending"; snapshot["ownerBudgetAuthorization"] = "pending"; snapshot["providerCapabilityProbe"] = "pending"; snapshot["providerAccountingStart"] = "pending"
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: snapshot)
    image = tmp_path / "image.json"; schedule = tmp_path / "schedule.json"
    budget = tmp_path / "budget.json"; capability = tmp_path / "capability.json"; ledger = tmp_path / "ledger.json"
    monkeypatch.setattr(evidence, "FIX5_LEDGER_PATH", ledger)
    _write(image, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "references": []})
    _write(schedule, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "schedule": snapshot["configuration"]["proposedTenRunSchedule"]})
    _write(budget, _fix5_authorization())
    monkeypatch.setattr(evidence, "FIX5_AUTHORIZATION_SHA256", evidence.sha(budget))
    _write(capability, {
        "status": "passed", "mode": "production-message", "workspaceHeaderConfigured": True,
        "workspaceId": evidence.FIX4_WORKSPACE_ID, "accountingMode": "uncapped",
        "paidMessageAuthorizedByCommand": True, "modelRequested": "claude-opus-5",
        "productionBinding": _production_binding(snapshot),
        "message": {"modelReturned": "claude-opus-5", "stopReason": "end_turn", "schemaValid": True, "selectionRejection": None, "referenceId": "ref-01", "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema"}},
    })
    _write(ledger, _uncapped_ledger())
    with pytest.raises(SystemExit, match="exact image hashes"):
        evidence.freeze(Namespace(image_approval=image, schedule_approval=schedule, budget_authorization=budget, provider_capability=capability, provider_ledger=ledger, output=tmp_path / "frozen.json"))


def test_freeze_rejects_stale_production_probe_binding(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot(); snapshot.pop("freezeDigest")
    snapshot["ownerImageApproval"] = "pending"; snapshot["ownerScheduleApproval"] = "pending"; snapshot["ownerBudgetAuthorization"] = "pending"; snapshot["providerCapabilityProbe"] = "pending"; snapshot["providerAccountingStart"] = "pending"
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: snapshot)
    image = tmp_path / "image.json"; schedule = tmp_path / "schedule.json"
    budget = tmp_path / "budget.json"; capability = tmp_path / "capability.json"; ledger = tmp_path / "ledger.json"
    monkeypatch.setattr(evidence, "FIX5_LEDGER_PATH", ledger)
    _write(image, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "references": snapshot["configuration"]["references"]})
    _write(schedule, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "schedule": snapshot["configuration"]["proposedTenRunSchedule"]})
    _write(budget, _fix5_authorization())
    monkeypatch.setattr(evidence, "FIX5_AUTHORIZATION_SHA256", evidence.sha(budget))
    stale = _production_binding(snapshot); stale["sourceSha256"] = "stale"
    _write(capability, {
        "status": "passed", "mode": "production-message", "workspaceHeaderConfigured": True,
        "workspaceId": evidence.FIX4_WORKSPACE_ID, "accountingMode": "uncapped",
        "paidMessageAuthorizedByCommand": True, "modelRequested": "claude-opus-5",
        "productionBinding": stale,
        "message": {"modelReturned": "claude-opus-5", "stopReason": "end_turn", "schemaValid": True, "selectionRejection": None, "referenceId": "ref-01", "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema"}},
    })
    _write(ledger, _uncapped_ledger())
    with pytest.raises(SystemExit, match="production-schema.*current"):
        evidence.freeze(Namespace(image_approval=image, schedule_approval=schedule, budget_authorization=budget, provider_capability=capability, provider_ledger=ledger, output=tmp_path / "frozen.json"))


def test_failed_runs_accept_owner_no_but_reject_yes(monkeypatch, capsys, tmp_path: Path) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    series = tmp_path / "series.jsonl"
    series.write_text("".join(json.dumps(_run(freeze, screenshot, index)) + "\n" for index in range(1, 11)), encoding="utf-8")
    judgments = tmp_path / "judgments.jsonl"
    evidence.summarize(Namespace(freeze=freeze_path, series=series, judgments=judgments))
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "complete": False, "failedOrInvalid": 10, "invalidSuccesses": 0, "ownerNo": 0, "ownerPending": 10,
        "ownerYes": 0, "qualityGatePassed": False, "runsRecorded": 10, "solvedValid": 0,
    }
    no_judgment = tmp_path / "no.json"; _write(no_judgment, {"generationId": "generation-1", "ownerJudgment": False})
    evidence.append_judgment(Namespace(freeze=freeze_path, series=series, judgment=no_judgment, judgments=judgments))
    yes_judgment = tmp_path / "yes.json"; _write(yes_judgment, {"generationId": "generation-2", "ownerJudgment": True})
    with pytest.raises(SystemExit, match="yes.*valid solved"):
        evidence.append_judgment(Namespace(freeze=freeze_path, series=series, judgment=yes_judgment, judgments=judgments))


def test_seven_yes_with_three_pending_is_incomplete(monkeypatch, capsys, tmp_path: Path, valid_designs: dict[str, dict]) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    runs = _series_runs(freeze, screenshot, valid_designs)
    series = tmp_path / "series.jsonl"; series.write_text("".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8")
    judgments = tmp_path / "judgments.jsonl"
    valid_indexes = [run["index"] for run in runs if run["validOutcome"]]
    records = [{"generationId": f"generation-{index}", "ownerJudgment": True, "recordedAt": "controlled", "freezeDigest": freeze["freezeDigest"], "runIndex": index} for index in valid_indexes[:7]]
    judgments.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    evidence.summarize(Namespace(freeze=freeze_path, series=series, judgments=judgments))
    result = json.loads(capsys.readouterr().out)
    assert result["ownerYes"] == 7
    assert result["ownerPending"] == 3
    assert result["complete"] is False
    assert result["qualityGatePassed"] is False


def test_complete_ten_outcome_judgments_can_pass(monkeypatch, capsys, tmp_path: Path, valid_designs: dict[str, dict]) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    runs = _series_runs(freeze, screenshot, valid_designs)
    series = tmp_path / "series.jsonl"; series.write_text("".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8")
    valid_indexes = [run["index"] for run in runs if run["validOutcome"]]
    judgments = tmp_path / "judgments.jsonl"
    records = [{
        "generationId": f"generation-{run['index']}",
        "ownerJudgment": run["index"] in valid_indexes[:7],
        "recordedAt": "controlled",
        "freezeDigest": freeze["freezeDigest"],
        "runIndex": run["index"],
    } for run in runs]
    judgments.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    evidence.summarize(Namespace(freeze=freeze_path, series=series, judgments=judgments))
    result = json.loads(capsys.readouterr().out)
    assert result["ownerYes"] == 7
    assert result["ownerNo"] == 3
    assert result["ownerPending"] == 0
    assert result["complete"] is True
    assert result["qualityGatePassed"] is True


def test_claimed_valid_design_rejects_empty_and_geometrically_invalid(
    tmp_path: Path,
    valid_designs: dict[str, dict],
) -> None:
    freeze = _snapshot()
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    empty = _run(freeze, screenshot, 1, outcome="solved", valid=True, design={})
    with pytest.raises(SystemExit, match="complete valid solved Design"):
        evidence._validate_runs([empty], freeze)

    invalid_design = deepcopy(valid_designs["ref-01"])
    invalid_design["placements"][0]["position"] = [999, 0, 999]
    invalid_design["fits"][0]["placement"]["position"] = [999, 0, 999]
    invalid = _run(freeze, screenshot, 1, outcome="solved", valid=True, design=invalid_design)
    with pytest.raises(SystemExit, match="authoritative placement"):
        evidence._validate_runs([invalid], freeze)


def test_claimed_valid_design_enforces_frozen_selection_scope_before_authority(
    monkeypatch,
    tmp_path: Path,
    valid_bed_rug_design: dict,
) -> None:
    freeze = _snapshot()
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    over_limit = deepcopy(valid_bed_rug_design)
    over_limit["intents"].append({
        **over_limit["intents"][1],
        "id": "second-rug",
    })
    over_limit["products"].append(deepcopy(over_limit["products"][1]))
    second_placement = deepcopy(over_limit["placements"][1])
    second_placement["instanceId"] = "second-rug"
    over_limit["placements"].append(second_placement)
    second_fit = deepcopy(over_limit["fits"][1])
    second_fit["placement"] = deepcopy(second_placement)
    over_limit["fits"].append(second_fit)
    run = _run(freeze, screenshot, 1, outcome="solved", valid=True, design=over_limit)

    def authority_must_not_run(*_args, **_kwargs):
        raise AssertionError("scope drift reached authoritative replay")

    monkeypatch.setattr(evidence, "resolve_design", authority_must_not_run)
    monkeypatch.setattr(evidence, "validate_circulation", authority_must_not_run)
    with pytest.raises(SystemExit, match="frozen selection scope"):
        evidence._validate_runs([run], freeze)


def test_claimed_valid_design_accepts_current_bed_only_and_bed_rug_scope(
    tmp_path: Path,
    valid_designs: dict[str, dict],
    valid_bed_rug_design: dict,
) -> None:
    freeze = _snapshot()
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    evidence._validate_runs([
        _run(freeze, screenshot, 1, outcome="solved", valid=True, design=valid_designs["ref-01"]),
    ], freeze)
    evidence._validate_runs([
        _run(freeze, screenshot, 1, outcome="solved", valid=True, design=valid_bed_rug_design),
    ], freeze)


def test_claimed_valid_design_preserves_historical_broader_scope(
    monkeypatch,
    tmp_path: Path,
    valid_bed_rug_design: dict,
) -> None:
    freeze = _snapshot()
    freeze["configuration"]["provider"].pop("selectionScope")
    nightstand_id = "nightstand-alkove-hayes-wild-oak"
    freeze["configuration"]["catalogue"]["eligibleProductIdsByReference"]["ref-01"].append(nightstand_id)
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    historical = deepcopy(valid_bed_rug_design)
    historical["intents"][1]["productId"] = nightstand_id
    historical["products"][1] = catalogue.get(nightstand_id).model_dump(mode="json")
    historical["placements"][1]["productId"] = nightstand_id
    historical["fits"][1]["placement"]["productId"] = nightstand_id
    run = _run(freeze, screenshot, 1, outcome="solved", valid=True, design=historical)

    def historical_authority_reached(*_args, **_kwargs):
        raise RuntimeError("historical authority reached")

    monkeypatch.setattr(evidence, "resolve_design", historical_authority_reached)
    with pytest.raises(RuntimeError, match="historical authority reached"):
        evidence._validate_runs([run], freeze)


def test_one_invalid_success_prevents_quality_pass(
    monkeypatch,
    capsys,
    tmp_path: Path,
    valid_designs: dict[str, dict],
) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    runs = _series_runs(freeze, screenshot, valid_designs)
    runs[-1] = _run(freeze, screenshot, 10, outcome="solved", valid=False, design={})
    series = tmp_path / "series.jsonl"; series.write_text("".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8")
    valid_indexes = [run["index"] for run in runs if run["validOutcome"]]
    judgments = tmp_path / "judgments.jsonl"
    records = [{
        "generationId": f"generation-{run['index']}",
        "ownerJudgment": run["index"] in valid_indexes[:7],
        "recordedAt": "controlled", "freezeDigest": freeze["freezeDigest"], "runIndex": run["index"],
    } for run in runs]
    judgments.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    evidence.summarize(Namespace(freeze=freeze_path, series=series, judgments=judgments))
    result = json.loads(capsys.readouterr().out)
    assert result["ownerPending"] == 0
    assert result["invalidSuccesses"] == 1
    assert result["qualityGatePassed"] is False


def test_technical_summary_requires_ten_server_valid_and_bound_render_passes(
    monkeypatch,
    capsys,
    tmp_path: Path,
    valid_designs: dict[str, dict],
) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    screenshot = tmp_path / "shot.png"; screenshot.write_bytes(b"png")
    runs = _series_runs(freeze, screenshot, valid_designs)
    series = tmp_path / "series.jsonl"
    series.write_text("".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8")

    evidence.technical_summary(Namespace(
        freeze=freeze_path, series=series, render_evidence=None,
    ))
    pending = json.loads(capsys.readouterr().out)
    assert pending["serverDesignValidityPassed"] is True
    assert pending["renderedEvidencePassed"] is False
    assert pending["technicalValidityPassed"] is False
    assert pending["aestheticOwnerGate"] == "deferred-separate-7-of-10-judgment"

    render_path = tmp_path / "render.json"
    _write(render_path, {
        "freezeDigest": freeze["freezeDigest"],
        "runs": [{"generationId": run["generationId"], "renderEvidenceValid": True} for run in runs],
    })
    evidence.technical_summary(Namespace(
        freeze=freeze_path, series=series, render_evidence=render_path,
    ))
    passed = json.loads(capsys.readouterr().out)
    assert passed["renderedValidDesigns"] == 10
    assert passed["technicalValidityPassed"] is True

    bad_render = tmp_path / "bad-render.json"
    _write(bad_render, {
        "freezeDigest": freeze["freezeDigest"],
        "runs": [{"generationId": runs[0]["generationId"], "renderEvidenceValid": True}],
    })
    with pytest.raises(SystemExit, match="exactly every"):
        evidence.technical_summary(Namespace(
            freeze=freeze_path, series=series, render_evidence=bad_render,
        ))


def test_runtime_deliverable_drift_rejects_current_freeze(monkeypatch, tmp_path: Path) -> None:
    freeze = _snapshot(); freeze_path = tmp_path / "freeze.json"; _write(freeze_path, freeze)
    current = _current_snapshot(freeze)
    current["runtimeDeliverables"] = deepcopy(current["runtimeDeliverables"])
    current["runtimeDeliverables"]["publicDecoders"]["sha256"] = "drifted-decoder"
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: current)
    with pytest.raises(SystemExit, match="runtime deliverables"):
        evidence._verify_freeze(freeze_path, require_current=True)


def test_current_freeze_audit_rejects_unrelated_empty_uncapped_ledger(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """INSPECT-5-F1: a shape-valid substitute cannot sever accounting history."""
    freeze = _snapshot()
    freeze_path = tmp_path / "substitute-freeze.json"
    _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    _write_overwrite_for_fixture(evidence.FIX5_LEDGER_PATH, {
        "version": 2,
        "accountingMode": "uncapped",
        "capUsd": None,
        "committedUsd": 0.0,
        "reservations": [],
        "migratedFrom": {"version": 1, "capUsd": 10.0},
    })

    with pytest.raises(SystemExit, match="lineage"):
        evidence._verify_freeze(freeze_path, require_current=True)


def test_current_freeze_audit_rejects_false_migration_metadata(monkeypatch, tmp_path: Path) -> None:
    freeze = _snapshot()
    freeze["providerAccountingMigration"] = {**freeze["providerAccountingMigration"], "historicalPrefixRows": 0}
    freeze.pop("freezeDigest")
    freeze["freezeDigest"] = hashlib.sha256(evidence.canonical(freeze)).hexdigest()
    freeze_path = tmp_path / "false-metadata-freeze.json"
    _write(freeze_path, freeze)
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: _current_snapshot(freeze))
    with pytest.raises(SystemExit, match="migration metadata"):
        evidence._verify_freeze(freeze_path, require_current=True)


def test_final_freeze_rejects_unrelated_empty_uncapped_ledger(monkeypatch, tmp_path: Path) -> None:
    substitute = {
        "version": 2, "accountingMode": "uncapped", "capUsd": None,
        "committedUsd": 0.0, "reservations": [],
        "migratedFrom": {"version": 1, "capUsd": 10.0},
    }
    args, _prepared, _ledger_path = _freeze_lineage_inputs(monkeypatch, tmp_path, substitute)
    with pytest.raises(SystemExit, match="lineage"):
        evidence.freeze(args)
    assert not args.output.exists()


def test_valid_migration_preserves_unknown_holds_and_allows_later_accounting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    migrated = _migrated_ledger()
    migrated["reservations"].extend([
        {"id": "new-settled", "status": "settled", "maximumUsd": 0.6048, "actualUsd": 0.2},
        {"id": "new-unknown", "status": "reserved-unknown", "maximumUsd": 0.6048},
    ])
    migrated["committedUsd"] += 0.8048
    args, prepared, ledger_path = _freeze_lineage_inputs(monkeypatch, tmp_path, migrated)
    evidence.freeze(args)
    frozen = json.loads(args.output.read_text(encoding="utf-8"))
    assert frozen["providerAccountingMigration"]["status"] == "completed-lineage-verified"
    assert frozen["providerAccountingStart"]["record"]["reservations"][0]["status"] == "reserved-unknown"
    assert evidence._verify_freeze(args.output, require_current=True, provider_ledger=ledger_path)["configuration"] == prepared["configuration"]

    later = deepcopy(migrated)
    later["reservations"].append({"id": "later-settled", "status": "settled", "maximumUsd": 0.6048, "actualUsd": 0.125})
    later["committedUsd"] += 0.125
    _write_overwrite_for_fixture(ledger_path, later)
    evidence._verify_freeze(args.output, require_current=True, provider_ledger=ledger_path)


@pytest.mark.parametrize("mutation", ["truncate", "reorder", "historical-change"])
def test_current_accounting_audit_rejects_historical_prefix_tampering(
    monkeypatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    migrated = _migrated_ledger()
    args, _prepared, ledger_path = _freeze_lineage_inputs(monkeypatch, tmp_path, migrated)
    evidence.freeze(args)
    changed = deepcopy(migrated)
    if mutation == "truncate":
        changed["reservations"] = changed["reservations"][1:]
    elif mutation == "reorder":
        changed["reservations"] = list(reversed(changed["reservations"]))
    else:
        changed["reservations"][0]["maximumUsd"] = 0.5
    changed["committedUsd"] = sum(
        row["maximumUsd"] if row["status"] == "reserved-unknown" else row["actualUsd"]
        for row in changed["reservations"]
    )
    _write_overwrite_for_fixture(ledger_path, changed)
    with pytest.raises(SystemExit, match="lineage"):
        evidence._verify_freeze(args.output, require_current=True, provider_ledger=ledger_path)


def test_current_accounting_audit_rejects_wrong_ledger_identity(monkeypatch, tmp_path: Path) -> None:
    args, _prepared, ledger_path = _freeze_lineage_inputs(monkeypatch, tmp_path, _migrated_ledger())
    evidence.freeze(args)
    wrong = tmp_path / "unrelated-ledger.json"
    _write(wrong, _migrated_ledger())
    with pytest.raises(SystemExit, match="wrong shared-ledger identity"):
        evidence._verify_freeze(args.output, require_current=True, provider_ledger=wrong)


def _write_overwrite_for_fixture(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_preliminary_builder_freeze_cannot_record_a_real_series(tmp_path: Path) -> None:
    freeze = _snapshot()
    freeze["version"] = evidence.PRELIMINARY_FREEZE_VERSION
    freeze["preliminaryBuilderFreeze"] = True
    freeze.pop("freezeDigest")
    freeze["freezeDigest"] = hashlib.sha256(evidence.canonical(freeze)).hexdigest()
    freeze_path = tmp_path / "preliminary.json"; _write(freeze_path, freeze)
    with pytest.raises(SystemExit, match="Only a final quality-freeze v5"):
        evidence._verify_freeze(freeze_path, require_current=False)


def test_fix4_accounting_evidence_rejects_wrong_workspace_old_final_and_malformed_rows(tmp_path: Path) -> None:
    authorization = _fix4_authorization()
    authorization["credentialWorkspaceId"] = "stale-workspace"
    with pytest.raises(SystemExit, match="authorization"):
        evidence._validate_fix4_authorization(authorization)

    historical = {
        "version": 1,
        "capUsd": 10.0,
        "committedUsd": 0.6048,
        "reservations": [{"id": "unknown", "status": "reserved-unknown", "maximumUsd": 0.6048}],
    }
    assert evidence._validate_accounting_state(historical, allow_historical_v1=True).startswith("historical")
    with pytest.raises(SystemExit, match="version or mode"):
        evidence._validate_accounting_state(historical, allow_historical_v1=False)

    malformed = _uncapped_ledger()
    malformed["reservations"] = [{"id": "sentinel", "status": "invented", "maximumUsd": 1.0}]
    with pytest.raises(SystemExit, match="reservation history"):
        evidence._validate_accounting_state(malformed, allow_historical_v1=False)

    freeze = _snapshot()
    freeze["version"] = "ticket-6-quality-freeze-v3"
    freeze.pop("freezeDigest")
    freeze["freezeDigest"] = hashlib.sha256(evidence.canonical(freeze)).hexdigest()
    freeze_path = tmp_path / "old-freeze.json"
    _write(freeze_path, freeze)
    with pytest.raises(SystemExit, match="quality-freeze v5"):
        evidence._verify_freeze(freeze_path, require_current=False)


def test_preliminary_freeze_records_historical_ledger_without_migrating_it(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.pop("freezeDigest")
    for key in (
        "ownerImageApproval", "ownerScheduleApproval", "ownerBudgetAuthorization",
        "providerCapabilityProbe", "providerAccountingStart",
    ):
        snapshot[key] = "pending"
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: deepcopy(snapshot))

    image = tmp_path / "image.json"
    schedule = tmp_path / "schedule.json"
    authorization = tmp_path / "authorization.json"
    ledger = tmp_path / "ledger.json"
    historical_path = tmp_path / "historical.json"
    output = tmp_path / "preliminary.json"
    _write(image, {
        "approved": True,
        "referenceSetVersion": evidence.REFERENCE_SET_VERSION,
        "references": snapshot["configuration"]["references"],
    })
    _write(schedule, {
        "approved": True,
        "referenceSetVersion": evidence.REFERENCE_SET_VERSION,
        "schedule": snapshot["configuration"]["proposedTenRunSchedule"],
    })
    monkeypatch.setattr(evidence, "FIX5_LEDGER_PATH", ledger)
    _write(historical_path, _historical_ledger())
    _write(ledger, _baseline_ledger())
    monkeypatch.setattr(evidence, "FIX4_HISTORICAL_LEDGER_SHA256", evidence.sha(historical_path))
    monkeypatch.setattr(evidence, "FIX5_MIGRATION_BASELINE_SHA256", evidence.sha(ledger))
    authorization_record = _fix5_authorization()
    _write(authorization, authorization_record)
    monkeypatch.setattr(evidence, "FIX5_AUTHORIZATION_SHA256", evidence.sha(authorization))
    original = ledger.read_bytes()

    evidence.preliminary_freeze(Namespace(
        image_approval=image,
        schedule_approval=schedule,
        budget_authorization=authorization,
        provider_ledger=ledger,
        historical_ledger=historical_path,
        output=output,
    ))

    assert ledger.read_bytes() == original
    frozen = json.loads(output.read_text(encoding="utf-8"))
    assert frozen["version"] == evidence.PRELIMINARY_FREEZE_VERSION
    assert frozen["providerAccountingMigration"]["status"] == "pending-host-post-inspection"
    assert frozen["providerAccountingMigration"]["preservedHistoricalPrefixRows"] == 1
    assert frozen["providerAccountingMigration"]["baselineRows"] == 2


def test_frozen_configuration_binds_complete_catalogue_for_every_reference() -> None:
    configuration = frozen_generation_configuration(catalogue)
    assert configuration["proposedTenRunSchedule"] == ["ref-01"] * 5 + ["ref-06"] * 5
    frozen_products = configuration["catalogue"]["products"]
    assert len(frozen_products) == len(catalogue.list()) == 20
    assert {item["id"] for item in frozen_products} == {product.id for product in catalogue.list()}
    assert set(configuration["catalogue"]["eligibleProductIdsByReference"]) == {
        reference["id"] for reference in configuration["references"]
    }
    assert set(configuration["catalogue"]["styleEligibleProductIdsByReference"]) == {
        reference["id"] for reference in configuration["references"]
    }
    for reference in configuration["references"]:
        style_expected = sorted(
            product.id for product in catalogue.list()
            if reference["privateStyleId"] in catalogue.private_style_ids(product.id)
            and "bedroom" in product.roomTypes
        )
        live_expected = sorted(
            product_id
            for product_id in style_expected
            if catalogue.get(product_id).category in {"bed", "rug"}
        )
        assert configuration["catalogue"]["styleEligibleProductIdsByReference"][reference["id"]] == style_expected
        assert configuration["catalogue"]["eligibleProductIdsByReference"][reference["id"]] == live_expected


def test_production_probe_reuses_exact_evidence_source_digest_and_contract() -> None:
    snapshot = evidence.prepared_snapshot()
    material = provider_probe.production_material("ref-01")
    binding = provider_probe.production_binding(material)
    assert binding["sourceSha256"] == snapshot["source"]["sha256"]
    assert binding["promptSha256"] == snapshot["configuration"]["promptContractSha256ByReference"]["ref-01"]
    assert binding["promptBytes"] == snapshot["configuration"]["promptContractBytesByReference"]["ref-01"]
    assert binding["schemaSha256"] == snapshot["configuration"]["providerOutputSchemaSha256"]
    assert binding["schemaBytes"] == snapshot["configuration"]["providerOutputSchemaBytes"]
