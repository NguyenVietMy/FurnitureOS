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
        "version": "ticket-6-quality-freeze-v3",
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
        "ownerBudgetAuthorization": {"record": "controlled"},
        "providerCapabilityProbe": {"record": "controlled"},
        "providerAccountingStart": {"record": "controlled"},
        "phoneGate": "waived",
        "configurationDigest": "configuration",
        "frozenAt": "controlled",
    }
    value["freezeDigest"] = hashlib.sha256(evidence.canonical(value)).hexdigest()
    return value


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
        "validation": "ProviderSelection plus shared Product/Room capabilities and graph policy",
    }


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
    _write(image, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "references": []})
    _write(schedule, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "schedule": snapshot["configuration"]["proposedTenRunSchedule"]})
    _write(budget, {"approved": True, "capUsd": 5.0, "accountingPath": str(tmp_path / "ledger.json")})
    _write(capability, {
        "status": "passed", "mode": "production-message", "workspaceHeaderConfigured": True,
        "paidMessageAuthorizedByCommand": True, "modelRequested": "claude-opus-5",
        "productionBinding": _production_binding(snapshot),
        "message": {"modelReturned": "claude-opus-5", "stopReason": "end_turn", "schemaValid": True, "selectionRejection": None, "referenceId": "ref-01", "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema"}},
    })
    _write(ledger, {"capUsd": 5.0, "committedUsd": 0.01})
    with pytest.raises(SystemExit, match="exact image hashes"):
        evidence.freeze(Namespace(image_approval=image, schedule_approval=schedule, budget_authorization=budget, provider_capability=capability, provider_ledger=ledger, output=tmp_path / "frozen.json"))


def test_freeze_rejects_stale_production_probe_binding(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot(); snapshot.pop("freezeDigest")
    snapshot["ownerImageApproval"] = "pending"; snapshot["ownerScheduleApproval"] = "pending"; snapshot["ownerBudgetAuthorization"] = "pending"; snapshot["providerCapabilityProbe"] = "pending"; snapshot["providerAccountingStart"] = "pending"
    monkeypatch.setattr(evidence, "prepared_snapshot", lambda: snapshot)
    image = tmp_path / "image.json"; schedule = tmp_path / "schedule.json"
    budget = tmp_path / "budget.json"; capability = tmp_path / "capability.json"; ledger = tmp_path / "ledger.json"
    _write(image, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "references": snapshot["configuration"]["references"]})
    _write(schedule, {"approved": True, "referenceSetVersion": evidence.REFERENCE_SET_VERSION, "schedule": snapshot["configuration"]["proposedTenRunSchedule"]})
    _write(budget, {"approved": True, "capUsd": 5.0, "accountingPath": str(tmp_path / "ledger.json")})
    stale = _production_binding(snapshot); stale["sourceSha256"] = "stale"
    _write(capability, {
        "status": "passed", "mode": "production-message", "workspaceHeaderConfigured": True,
        "paidMessageAuthorizedByCommand": True, "modelRequested": "claude-opus-5",
        "productionBinding": stale,
        "message": {"modelReturned": "claude-opus-5", "stopReason": "end_turn", "schemaValid": True, "selectionRejection": None, "referenceId": "ref-01", "settings": {"thinking": "adaptive", "effort": "high", "format": "json_schema"}},
    })
    _write(ledger, {"capUsd": 5.0, "committedUsd": 0.725615})
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


def test_preliminary_builder_freeze_cannot_record_a_real_series(tmp_path: Path) -> None:
    freeze = _snapshot()
    freeze["version"] = "ticket-6-preliminary-builder-freeze-fix-2-v1"
    freeze["preliminaryBuilderFreeze"] = True
    freeze.pop("freezeDigest")
    freeze["freezeDigest"] = hashlib.sha256(evidence.canonical(freeze)).hexdigest()
    freeze_path = tmp_path / "preliminary.json"; _write(freeze_path, freeze)
    with pytest.raises(SystemExit, match="Only a final quality-freeze v3"):
        evidence._verify_freeze(freeze_path, require_current=False)


def test_frozen_configuration_binds_complete_catalogue_for_every_reference() -> None:
    configuration = frozen_generation_configuration(catalogue)
    assert configuration["proposedTenRunSchedule"] == ["ref-01"] * 5 + ["ref-06"] * 5
    frozen_products = configuration["catalogue"]["products"]
    assert len(frozen_products) == len(catalogue.list()) == 20
    assert {item["id"] for item in frozen_products} == {product.id for product in catalogue.list()}
    assert set(configuration["catalogue"]["eligibleProductIdsByReference"]) == {
        reference["id"] for reference in configuration["references"]
    }
    for reference in configuration["references"]:
        expected = sorted(
            product.id for product in catalogue.list()
            if reference["privateStyleId"] in catalogue.private_style_ids(product.id)
            and "bedroom" in product.roomTypes
        )
        assert configuration["catalogue"]["eligibleProductIdsByReference"][reference["id"]] == expected


def test_production_probe_reuses_exact_evidence_source_digest_and_contract() -> None:
    snapshot = evidence.prepared_snapshot()
    material = provider_probe.production_material("ref-01")
    binding = provider_probe.production_binding(material)
    assert binding["sourceSha256"] == snapshot["source"]["sha256"]
    assert binding["promptSha256"] == snapshot["configuration"]["promptContractSha256ByReference"]["ref-01"]
    assert binding["promptBytes"] == snapshot["configuration"]["promptContractBytesByReference"]["ref-01"]
    assert binding["schemaSha256"] == snapshot["configuration"]["providerOutputSchemaSha256"]
    assert binding["schemaBytes"] == snapshot["configuration"]["providerOutputSchemaBytes"]
