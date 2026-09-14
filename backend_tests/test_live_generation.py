from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from time import monotonic
import time

import httpx
import pytest
from pydantic import ValidationError

import api.arrangement as arrangement_module
import api.domain as domain_module
import api.live_generation as live_generation
from api.arrangement import ArrangementSession, resolve_arrangement
from api.catalogue import catalogue
from api.catalogue.contract import CatalogueQuery
from api.design import intent_fixture_room
from api.domain import rectangular_room_shell, resolve_design, wall_placement_capabilities
from api.live_generation import (
    LiveGenerationRequest,
    LiveGenerationFailure,
    ProviderSelection,
    _output_schema,
    generate_live_bedroom,
    public_config,
    reference_manifest,
    verified_reference,
)
from api.models import ArrangementRequest, ArrangementSelection, DesignRequest
from api.provider import (
    AnthropicProvider,
    BudgetLedger,
    MODEL_ID,
    ProviderCallError,
    ProviderReply,
    ProviderSettings,
    ProviderUsage,
    _jpeg_dimensions,
)


BED = "bed-prudence-tufted-queen-natural"
CONTROLLED_IMAGE_BASE64 = base64.b64encode(Path("public/style-references/ref-02.jpg").read_bytes()).decode("ascii")


def selection(*intents: dict) -> dict:
    return {"intents": list(intents)}


def bed_intent(*, wall: str = "wall-north") -> dict:
    return {"id": "anchor-bed", "kind": "against", "productId": BED, "wallId": wall, "face": "back"}


class TranscriptProvider:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ProviderReply):
            return outcome
        return ProviderReply(
            payload=outcome,
            model=MODEL_ID,
            stop_reason="end_turn",
            usage=ProviderUsage(inputTokens=100, outputTokens=25, costUsd=0.001125),
            latency_ms=3,
        )


def test_reference_bytes_and_public_config_preserve_provenance_without_private_styles(monkeypatch) -> None:
    for name in (
        "FURNITUREOS_LIVE_GENERATION_ENABLED", "ANTHROPIC_API_KEY", "ANTHROPIC_CREDENTIAL_FILE",
        "ANTHROPIC_WORKSPACE_ID", "FURNITUREOS_GENERATION_SPEND_CAP_USD",
        "FURNITUREOS_GENERATION_ACCOUNTING_PATH", "VERCEL",
    ):
        monkeypatch.delenv(name, raising=False)
    manifest = reference_manifest()
    assert len(manifest.images) == 6
    for record in manifest.images:
        data = verified_reference(record)
        assert len(data) == record.bytes
        assert hashlib.sha256(data).hexdigest() == record.sha256
        width, height = _jpeg_dimensions(data)
        assert sorted((width, height)) == [1200, 1800] or sorted((width, height)) == [800, 1200]
        assert ((width + 27) // 28) * ((height + 27) // 28) <= 2_795

    payload = public_config().model_dump_json()
    assert "privateStyle" not in payload
    assert "Warm Minimal" not in payload
    assert '"referenceApproval":"approved"' in payload
    assert '"phoneGate":"waived"' in payload


def test_reference_static_route_and_vercel_package_cover_the_verified_server_path(client) -> None:
    record = reference_manifest().images[0]
    response = client.get(f"/style-references/{record.fileName}")
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == record.sha256
    vercel = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    included = vercel["functions"]["api/index.py"]["includeFiles"]
    assert "api/**" in included
    assert "public/style-references/**" in included


def test_public_availability_requires_complete_current_account_configuration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FURNITUREOS_LIVE_GENERATION_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "controlled")
    monkeypatch.setenv("FURNITUREOS_GENERATION_SPEND_CAP_USD", "5")
    monkeypatch.setenv("FURNITUREOS_GENERATION_ACCOUNTING_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    assert public_config().realCallsEnabled is False
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "controlled-workspace")
    assert public_config().realCallsEnabled is True
    assert ProviderSettings.from_environment().spend_cap_usd == 5.0
    monkeypatch.setenv("FURNITUREOS_GENERATION_SPEND_CAP_USD", "6")
    assert public_config().realCallsEnabled is False
    with pytest.raises(ProviderCallError, match="USD 5.00"):
        ProviderSettings.from_environment()


def test_public_availability_accepts_workspace_from_controlled_external_file(monkeypatch, tmp_path: Path) -> None:
    credential = tmp_path / "controlled.env.local"
    credential.write_text("ANTHROPIC_API_KEY=controlled\nANTHROPIC_WORKSPACE_ID=controlled-workspace\n", encoding="utf-8")
    monkeypatch.setenv("FURNITUREOS_LIVE_GENERATION_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_CREDENTIAL_FILE", str(credential))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.setenv("FURNITUREOS_GENERATION_SPEND_CAP_USD", "5")
    monkeypatch.setenv("FURNITUREOS_GENERATION_ACCOUNTING_PATH", str(tmp_path / "ledger.json"))
    assert public_config().realCallsEnabled is True


def test_live_generation_sends_real_reference_pixels_and_solves_once() -> None:
    provider = TranscriptProvider([selection(bed_intent())])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
        generation_id_factory=lambda: "generation-controlled-1",
    )

    assert result.status == "solved"
    assert result.generationId == "generation-controlled-1"
    assert result.providerCalls == 1
    assert len(result.design.arrangementHistory.attempts) == 1
    assert result.design.arrangementHistory.maxSolveAttempts == 3
    sent = base64.b64decode(provider.calls[0]["image_base64"])
    assert hashlib.sha256(sent).hexdigest() == reference_manifest().images[0].sha256
    prompt = json.loads(provider.calls[0]["prompt_text"])
    assert prompt["repairNumber"] == 0
    assert prompt["previousSelection"] is None
    assert "Warm Minimal" not in provider.calls[0]["prompt_text"]


def test_failed_repair_retains_history_and_unknown_usage_without_drops() -> None:
    initial = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    provider = TranscriptProvider([
        initial,
        ProviderCallError("transport-error", "Controlled transport failure.", attempted=True),
    ])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
        generation_id_factory=lambda: "generation-controlled-2",
    )

    assert result.status == "failed"
    assert result.code == "transport-error"
    assert result.providerCalls == 2
    assert result.usage.known is False
    assert result.designFailure is not None
    history = result.designFailure.arrangementHistory
    assert [attempt.stage for attempt in history.attempts] == ["initial"]
    assert history.attempts[0].outcome == "placement-failed"
    assert history.maxSolveAttempts == 3 + 1
    assert all(attempt.stage != "drop" for attempt in history.attempts)
    repair_prompt = json.loads(provider.calls[1]["prompt_text"])
    assert [item["id"] for item in repair_prompt["previousSelection"]["intents"]] == ["anchor-bed", "storage"]
    assert repair_prompt["previousSelection"]["intents"][1]["productId"] == "wardrobe-movian-cinca-five-door"
    assert repair_prompt["actualPrecedingFeedback"]["outcome"] == "placement-failed"
    assert len(repair_prompt["chronologicalHistory"]) == 1


def test_valid_repair_uses_actual_feedback_and_does_not_replay_initial() -> None:
    initial = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    repaired = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-fils-two-door", "wallId": "wall-east", "face": "back"},
    )
    provider = TranscriptProvider([initial, repaired])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )
    assert result.status == "solved"
    assert result.providerCalls == 2
    assert [attempt.stage for attempt in result.design.arrangementHistory.attempts] == ["initial", "repair"]
    assert result.design.arrangementHistory.attempts[1].changedRequestIds == ("storage",)
    assert result.design.arrangementHistory.totalAttemptedCandidates <= 2 * 256


@pytest.mark.parametrize("outcomes", [
    [selection(bed_intent())],
    [
        selection(
            bed_intent(),
            {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
        ),
        selection(
            bed_intent(),
            {"id": "storage", "kind": "against", "productId": "wardrobe-movian-fils-two-door", "wallId": "wall-east", "face": "back"},
        ),
    ],
])
def test_live_generation_derives_zone_offer_once_across_initial_and_repair(monkeypatch, outcomes) -> None:
    calls = 0
    original = live_generation.derive_zones

    def counted(room):
        nonlocal calls
        calls += 1
        return original(room)

    monkeypatch.setattr(live_generation, "derive_zones", counted)
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider(outcomes),
    )
    assert result.status == "solved"
    assert calls == 1


def test_zoned_initial_and_repair_reuse_one_offer_across_all_solver_aliases(monkeypatch) -> None:
    room = intent_fixture_room()
    original = live_generation.derive_zones
    offered = original(room)
    zone = max(
        offered.zones,
        key=lambda item: (item.bounds.maxX - item.bounds.minX) * (item.bounds.maxZ - item.bounds.minZ),
    )
    calls = {"live": 0, "arrangement": 0, "domain": 0}

    def counted(alias: str):
        def derive(value):
            calls[alias] += 1
            return original(value)
        return derive

    monkeypatch.setattr(live_generation, "derive_zones", counted("live"))
    monkeypatch.setattr(arrangement_module, "derive_zones", counted("arrangement"))
    monkeypatch.setattr(domain_module, "derive_zones", counted("domain"))
    initial = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
        {"id": "rug", "kind": "in_zone", "productId": "rug-ravenna-prospect-moroccan", "zoneId": zone.id},
    )
    repair = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-fils-two-door", "wallId": "wall-east", "face": "back"},
        {"id": "rug", "kind": "in_zone", "productId": "rug-stone-beam-jute-natural", "zoneId": zone.id},
    )
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([initial, repair]),
    )
    assert result.status == "solved"
    assert result.providerCalls == 2
    assert calls == {"live": 1, "arrangement": 0, "domain": 0}


def test_optional_drop_waits_until_two_valid_repairs_are_exhausted() -> None:
    blocked = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([blocked, blocked, blocked]),
    )
    assert result.status == "solved"
    assert result.providerCalls == 3
    assert [attempt.stage for attempt in result.design.arrangementHistory.attempts] == [
        "initial", "repair", "repair", "drop",
    ]
    assert result.design.arrangementHistory.attempts[-1].droppedRequestIds == ("storage",)
    assert len(result.design.arrangementHistory.attempts) <= 23


def test_invalid_repair_category_terminates_without_optional_drop() -> None:
    initial = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    changed_category = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "dresser-stone-beam-brecken-brown", "wallId": "wall-south", "face": "back"},
    )
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([initial, changed_category, changed_category]),
    )
    assert result.status == "failed"
    assert result.code == "selection-correction-exhausted"
    assert result.providerCalls == 3
    assert [item.code for item in result.selectionRejections] == [
        "repair-category-error", "repair-category-error",
    ]
    assert result.designFailure is not None
    assert [attempt.stage for attempt in result.designFailure.arrangementHistory.attempts] == ["initial"]
    assert all(attempt.stage != "drop" for attempt in result.designFailure.arrangementHistory.attempts)


@pytest.mark.parametrize("bad_payload", [
    {"intents": [{**bed_intent(), "position": [0, 0, 0]}]},
    selection(bed_intent(), {"id": "second-bed", "kind": "against", "productId": BED, "wallId": "wall-south", "face": "back"}),
    selection({"id": "not-anchor", "kind": "against", "productId": BED, "wallId": "wall-north", "face": "back"}),
    selection(bed_intent(), {"id": "bad-ref", "kind": "adjacent_to", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "missing", "side": "right", "gapM": 0}),
])
def test_three_invalid_provider_selections_fail_closed_without_solver_success(bad_payload: dict) -> None:
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([bad_payload, bad_payload, bad_payload]),
    )
    assert result.status == "failed"
    assert result.code == "selection-correction-exhausted"
    assert result.providerCalls == 3
    assert len(result.selectionRejections) == 3
    assert result.designFailure is None


def test_three_invalid_drafts_account_unknown_usage_without_claiming_complete_total() -> None:
    invalid = selection({**bed_intent(), "unexpected": "bounded"})
    unknown = ProviderReply(
        payload=invalid,
        model=MODEL_ID,
        stop_reason="end_turn",
        usage=None,
        latency_ms=1,
    )
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([invalid, unknown, invalid]),
    )
    assert result.status == "failed"
    assert result.providerCalls == 3
    assert result.usage.known is False
    assert len(result.selectionRejections) == 3


def test_no_style_eligible_bed_fails_before_provider_call() -> None:
    provider = TranscriptProvider([])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-05"),
        provider=provider,
    )
    assert result.status == "failed"
    assert result.code == "eligible-catalogue-error"
    assert result.providerCalls == 0
    assert provider.calls == []


def test_provider_schema_projection_removes_unsupported_constraints() -> None:
    schema_text = json.dumps(_output_schema())
    for keyword in (
        '"minimum"', '"maximum"', '"exclusiveMinimum"', '"exclusiveMaximum"',
        '"minLength"', '"maxLength"', '"pattern"', '"minItems"', '"maxItems"',
    ):
        assert keyword not in schema_text
    assert "enforced by the server" in schema_text


def test_provider_schema_is_strict_anyof_with_only_per_operation_fields() -> None:
    schema = _output_schema()
    items = schema["properties"]["intents"]["items"]
    assert "anyOf" in items and len(items["anyOf"]) == 7
    expected = {
        "ProviderAgainstIntent": {"id", "productId", "kind", "wallId", "face"},
        "ProviderCentredIntent": {"id", "productId", "kind", "wallId", "face"},
        "ProviderCornerIntent": {"id", "productId", "kind", "wallId", "face", "adjacentWallId"},
        "ProviderAdjacentIntent": {"id", "productId", "kind", "referenceId", "side", "gapM"},
        "ProviderFacingIntent": {"id", "productId", "kind", "referenceId", "gapM"},
        "ProviderFlankingIntent": {"id", "productId", "kind", "referenceId", "side", "gapM"},
        "ProviderZoneIntent": {"id", "productId", "kind", "zoneId"},
    }
    for name, fields in expected.items():
        definition = schema["$defs"][name]
        assert definition["additionalProperties"] is False
        assert set(definition["properties"]) == fields
        assert set(definition["required"]) == fields
        assert all("default" not in value for value in definition["properties"].values())

    with pytest.raises(ValidationError):
        ProviderSelection.model_validate(selection({**bed_intent(), "zoneId": "sleep-zone"}))
    with pytest.raises(ValidationError):
        ProviderSelection.model_validate(selection({
            "id": "rug", "kind": "in_zone", "productId": "rug-ravenna-prospect-moroccan",
            "zoneId": "sleep-zone", "wallId": "wall-north",
        }))


def test_shared_wall_capabilities_exclude_empty_faces_and_back_only_corners() -> None:
    room = intent_fixture_room()
    lamp = catalogue.get("lamp-rivet-harper-brass")
    wardrobe = catalogue.get("wardrobe-movian-cinca-five-door")
    nightstand = catalogue.get("nightstand-alkove-hayes-wild-oak")
    assert lamp is not None and wardrobe is not None and nightstand is not None
    assert wall_placement_capabilities(room, lamp) == ()
    wardrobe_options = wall_placement_capabilities(room, wardrobe)
    assert wardrobe_options
    assert {item.face for item in wardrobe_options} == {"back"}
    assert all(item.kind != "in_corner" for item in wardrobe_options)

    corner_options = [item for item in wall_placement_capabilities(room, nightstand) if item.kind == "in_corner"]
    assert corner_options
    for option in corner_options:
        result = resolve_design(catalogue, DesignRequest.model_validate({
            "room": room.model_dump(mode="json"),
            "intents": [{
                "id": "nightstand", "kind": "in_corner", "productId": nightstand.id,
                "wallId": option.wall_id, "face": option.face,
                "adjacentWallId": option.adjacent_wall_id,
            }],
            "maxCandidates": 256,
        }))
        if result.status == "failed":
            assert result.reason not in {
                "unknown-wall-reference", "nonadjacent-corner-walls",
                "corner-angle-not-supported", "product-face-not-supported",
            }


def test_invalid_initial_is_corrected_without_establishing_identity_or_solve() -> None:
    invalid = selection(
        bed_intent(),
        {"id": "lamp", "kind": "against", "productId": "lamp-rivet-harper-brass", "wallId": "wall-east", "face": "back"},
    )
    provider = TranscriptProvider([invalid, selection(bed_intent())])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )
    assert result.status == "solved"
    assert result.providerCalls == 2
    assert [item.code for item in result.selectionRejections] == ["wall-face-error"]
    assert len(result.design.arrangementHistory.attempts) == 1
    correction_prompt = json.loads(provider.calls[1]["prompt_text"])
    assert correction_prompt["validSelectionNumber"] == 0
    assert correction_prompt["immutableRepairContract"] is None
    assert correction_prompt["actualPrecedingFeedback"] is None
    assert correction_prompt["correctionFeedback"]["code"] == "wall-face-error"


def test_invalid_repair_consumes_call_but_preserves_history_then_valid_last_call() -> None:
    initial = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    invalid_repair = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "dresser-stone-beam-brecken-brown", "wallId": "wall-south", "face": "back"},
    )
    valid_repair = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-fils-two-door", "wallId": "wall-east", "face": "back"},
    )
    provider = TranscriptProvider([initial, invalid_repair, valid_repair])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )
    assert result.status == "solved"
    assert result.providerCalls == 3
    assert [item.code for item in result.selectionRejections] == ["repair-category-error"]
    assert [item.stage for item in result.design.arrangementHistory.attempts] == ["initial", "repair"]
    last_prompt = json.loads(provider.calls[2]["prompt_text"])
    assert last_prompt["validSelectionNumber"] == 1
    assert len(last_prompt["chronologicalHistory"]) == 1
    assert last_prompt["correctionFeedback"]["code"] == "repair-category-error"


def test_invalid_drafts_cannot_unlock_optional_drops() -> None:
    blocked = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    invalid = selection({**bed_intent(), "unknownProviderField": "sentinel"})
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([blocked, invalid, invalid]),
    )
    assert result.status == "failed"
    assert result.code == "selection-correction-exhausted"
    assert result.designFailure is not None
    assert [item.stage for item in result.designFailure.arrangementHistory.attempts] == ["initial"]
    assert len(result.selectionRejections) == 2


def test_rejection_path_and_intent_id_omit_arbitrary_provider_sentinels() -> None:
    sentinel = "SECRET/../unknown-field"
    malformed = selection({
        "id": sentinel,
        "kind": "against",
        "productId": BED,
        "wallId": "wall-north",
        "face": "back",
        sentinel: "do-not-publish",
    })
    provider = TranscriptProvider([malformed, selection(bed_intent())])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )
    assert result.status == "solved"
    rejection = result.selectionRejections[0]
    assert rejection.code == "operation-shape-error"
    assert rejection.intentId is None
    assert sentinel not in (rejection.path or "")
    assert sentinel not in rejection.detail
    correction_prompt = provider.calls[1]["prompt_text"]
    assert "do-not-publish" not in correction_prompt
    assert LiveGenerationFailure.model_json_schema()["properties"]["selectionRejections"]["maxItems"] == 3


@pytest.mark.parametrize(("invalid_repair", "expected_code"), [
    (
        selection(
            bed_intent(),
            {"id": "renamed", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
        ),
        "repair-identity-error",
    ),
    (
        selection(
            bed_intent(wall="wall-south"),
            {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
        ),
        "repair-anchor-error",
    ),
    (
        selection(
            bed_intent(),
            {"id": "storage", "kind": "against", "productId": "dresser-stone-beam-brecken-brown", "wallId": "wall-south", "face": "back"},
        ),
        "repair-category-error",
    ),
])
def test_invalid_repairs_report_typed_immutable_contract_errors(invalid_repair: dict, expected_code: str) -> None:
    initial = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([initial, invalid_repair, invalid_repair]),
    )
    assert result.status == "failed"
    assert result.code == "selection-correction-exhausted"
    assert {item.code for item in result.selectionRejections} == {expected_code}
    assert result.designFailure is not None
    assert [item.stage for item in result.designFailure.arrangementHistory.attempts] == ["initial"]


def test_all_initial_and_worst_bounded_correction_prompts_fit_32k() -> None:
    room = intent_fixture_room()
    zone_offer = live_generation.derive_zones(room)
    initial_sizes = {}
    for reference in reference_manifest().images:
        eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
        prompt = live_generation._prompt(
            eligible=eligible,
            room=room,
            zone_offer=zone_offer,
            capabilities=live_generation._wall_capability_map(room, eligible),
            provider_call_index=0,
            previous=None,
            session=None,
        )
        initial_sizes[reference.id] = len(prompt.encode("utf-8"))
    assert set(initial_sizes) == {f"ref-0{index}" for index in range(1, 7)}
    assert max(initial_sizes.values()) <= live_generation.MAX_PROMPT_TEXT_BYTES

    blocked = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-cinca-five-door", "wallId": "wall-east", "face": "back"},
    )
    long_value = "a" * 100
    maximal_invalid = {"intents": [{
        "id": "a" * 64,
        "kind": "against",
        "productId": long_value,
        "wallId": long_value,
        "face": long_value,
        "adjacentWallId": long_value,
        "zoneId": long_value,
        "referenceId": "b" * 64,
        "side": long_value,
        "gapM": 1000,
    } for _ in range(20)]}
    repaired = selection(
        bed_intent(),
        {"id": "storage", "kind": "against", "productId": "wardrobe-movian-fils-two-door", "wallId": "wall-east", "face": "back"},
    )
    provider = TranscriptProvider([blocked, maximal_invalid, repaired])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )
    assert result.status == "solved"
    correction_sizes = [len(call["prompt_text"].encode("utf-8")) for call in provider.calls]
    assert len(correction_sizes) == 3
    assert max(correction_sizes) <= live_generation.MAX_PROMPT_TEXT_BYTES
    assert len(json.dumps(json.loads(provider.calls[2]["prompt_text"])["rejectedDraft"], separators=(",", ":")).encode()) <= live_generation.MAX_REJECTED_DRAFT_BYTES

    two_history_provider = TranscriptProvider([blocked, blocked, blocked])
    drop_result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=two_history_provider,
    )
    assert drop_result.status == "solved"
    history_sizes = [len(call["prompt_text"].encode("utf-8")) for call in two_history_provider.calls]
    assert max([*initial_sizes.values(), *correction_sizes, *history_sizes]) <= live_generation.MAX_PROMPT_TEXT_BYTES


def test_legacy_arrangement_cap_and_incremental_initial_binding_are_preserved() -> None:
    initial = ArrangementSelection.model_validate({"id": "initial", "intents": [bed_intent()]})
    request = ArrangementRequest.model_validate({
        "room": intent_fixture_room().model_dump(mode="json"),
        "selections": [
            initial.model_dump(mode="json"),
            {**initial.model_dump(mode="json"), "id": "repair-1"},
            {**initial.model_dump(mode="json"), "id": "repair-2"},
        ],
        "policies": [{"requestId": "anchor-bed", "required": True, "anchor": True}],
        "clearanceWidthM": 0.6,
        "maxCandidates": 256,
    })
    legacy = resolve_arrangement(catalogue, request)
    assert legacy.status == "solved"
    assert legacy.arrangementHistory.maxSolveAttempts == 3

    session = ArrangementSession(catalogue, request)
    wrong = ArrangementSelection.model_validate({**initial.model_dump(mode="json"), "id": "wrong"})
    with pytest.raises(ValueError, match="configured initial"):
        session.submit(wrong)


def test_zone_failure_is_terminal_and_cannot_repeat_attempt_id() -> None:
    room = rectangular_room_shell("too-large-for-zones", 40, 40, 3)
    zone_intent = {"id": "anchor-bed", "kind": "in_zone", "productId": BED, "zoneId": "unknown"}
    selection_value = ArrangementSelection.model_validate({"id": "initial", "intents": [zone_intent]})
    request = ArrangementRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "selections": [selection_value.model_dump(mode="json")],
        "policies": [{"requestId": "anchor-bed", "required": True, "anchor": True}],
        "clearanceWidthM": 0.6,
    })
    session = ArrangementSession(catalogue, request, selection_limit=3)
    assert session.submit(selection_value) is None
    with pytest.raises(RuntimeError, match="already finished"):
        session.submit(selection_value.model_copy(update={"id": "repair-1"}))
    assert [attempt.id for attempt in session.attempts] == ["attempt-1"]


def test_workspace_header_and_exact_provider_contract_on_all_endpoints(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.startswith("/v1/models/"):
            return httpx.Response(200, json={"id": MODEL_ID})
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 500})
        output = json.dumps(selection(bed_intent()))
        return httpx.Response(200, json={
            "model": MODEL_ID,
            "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": "not parsed"}, {"type": "text", "text": output}],
            "usage": {"input_tokens": 500, "output_tokens": 50},
        })

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    provider = AnthropicProvider(ProviderSettings(
        api_key="controlled-not-a-secret",
        workspace_id="workspace-controlled",
        spend_cap_usd=20.0,
        accounting_path=tmp_path / "ledger.json",
    ), client=client)
    provider.retrieve_model(monotonic() + 5)
    reply = provider.generate(
        prompt_text="controlled",
        image_media_type="image/jpeg",
        image_base64=CONTROLLED_IMAGE_BASE64,
        output_schema=_output_schema(),
        deadline_at=monotonic() + 5,
    )
    assert reply.model == MODEL_ID
    assert [request.url.path for request in seen] == [
        f"/v1/models/{MODEL_ID}", "/v1/messages/count_tokens", "/v1/messages",
    ]
    assert all(request.headers["anthropic-workspace-id"] == "workspace-controlled" for request in seen)
    message_body = json.loads(seen[-1].content)
    assert message_body["thinking"] == {"type": "adaptive"}
    assert message_body["output_config"]["effort"] == "high"
    assert message_body["output_config"]["format"]["type"] == "json_schema"
    count_body = json.loads(seen[-2].content)
    assert "max_tokens" not in count_body
    assert message_body["max_tokens"] == 8192
    assert count_body == {key: value for key, value in message_body.items() if key != "max_tokens"}


def test_ledger_persists_actual_over_reservation_and_fails_closed(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger = BudgetLedger(ledger_path, 8.5)
    reservation, maximum = ledger.reserve(1)
    assert 0.60 < maximum < 0.61
    with pytest.raises(ProviderCallError, match="exceeded"):
        ledger.settle(reservation, ProviderUsage(inputTokens=1_100_000, outputTokens=10_000, costUsd=8.0))
    state = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert state["committedUsd"] == pytest.approx(8.0)
    assert state["reservations"][0]["status"] == "settled-over-reservation"
    with pytest.raises(ProviderCallError, match="no room"):
        ledger.reserve(1)


@pytest.mark.parametrize(
    ("model", "stop_reason"),
    (("another-model", "end_turn"), (MODEL_ID, "max_tokens"), (MODEL_ID, "refusal")),
)
def test_provider_rejects_model_or_stop_reason_drift(tmp_path: Path, model: str, stop_reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 10})
        return httpx.Response(200, json={
            "model": model,
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": json.dumps(selection(bed_intent()))}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    provider = AnthropicProvider(ProviderSettings(
        api_key="controlled",
        workspace_id=None,
        spend_cap_usd=20,
        accounting_path=tmp_path / "ledger.json",
    ), client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))
    with pytest.raises(ProviderCallError) as caught:
        provider.generate(
            prompt_text="controlled",
            image_media_type="image/jpeg",
        image_base64=CONTROLLED_IMAGE_BASE64,
            output_schema=_output_schema(),
            deadline_at=monotonic() + 5,
        )
    assert caught.value.code == "schema-error"
    assert caught.value.attempted is True
    assert caught.value.usage == ProviderUsage(inputTokens=10, outputTokens=5, costUsd=0.000175)
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["reservations"][0]["status"] == "settled"
    assert ledger["committedUsd"] == pytest.approx(0.000175)


def test_provider_settles_bounded_usage_supplied_with_non_2xx_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 10})
        return httpx.Response(400, json={
            "type": "error",
            "error": {"type": "invalid_request_error", "message": "must stay private"},
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    provider = AnthropicProvider(ProviderSettings(
        api_key="controlled",
        workspace_id=None,
        spend_cap_usd=20,
        accounting_path=tmp_path / "ledger.json",
    ), client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))
    with pytest.raises(ProviderCallError) as caught:
        provider.generate(
            prompt_text="controlled",
            image_media_type="image/jpeg",
            image_base64=CONTROLLED_IMAGE_BASE64,
            output_schema=_output_schema(),
            deadline_at=monotonic() + 5,
        )
    assert caught.value.code == "provider-error"
    assert caught.value.detail == "Provider request failed with HTTP 400."
    assert "must stay private" not in caught.value.detail
    assert caught.value.attempted is True
    assert caught.value.usage == ProviderUsage(inputTokens=10, outputTokens=5, costUsd=0.000175)
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["reservations"][0]["status"] == "settled"
    assert ledger["committedUsd"] == pytest.approx(0.000175)


def test_provider_retains_reservation_when_non_2xx_usage_is_malformed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 10})
        return httpx.Response(429, json={"usage": {"input_tokens": "bad", "output_tokens": 5}})

    provider = AnthropicProvider(ProviderSettings(
        api_key="controlled",
        workspace_id=None,
        spend_cap_usd=20,
        accounting_path=tmp_path / "ledger.json",
    ), client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))
    with pytest.raises(ProviderCallError) as caught:
        provider.generate(
            prompt_text="controlled",
            image_media_type="image/jpeg",
            image_base64=CONTROLLED_IMAGE_BASE64,
            output_schema=_output_schema(),
            deadline_at=monotonic() + 5,
        )
    assert caught.value.code == "rate-limit"
    assert caught.value.usage is None
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["reservations"][0]["status"] == "reserved-unknown"
    assert ledger["committedUsd"] == pytest.approx(0.6048)


def test_provider_streams_and_stops_oversized_response_before_messages(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"x" * (1_048_576 + 1))

    provider = AnthropicProvider(ProviderSettings(
        api_key="controlled", workspace_id=None, spend_cap_usd=1,
        accounting_path=tmp_path / "ledger.json",
    ), client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))
    with pytest.raises(ProviderCallError, match="1 MiB") as caught:
        provider.generate(
            prompt_text="controlled",
            image_media_type="image/jpeg",
            image_base64=CONTROLLED_IMAGE_BASE64,
            output_schema=_output_schema(),
            deadline_at=monotonic() + 5,
        )
    assert caught.value.attempted is False
    assert calls == 1


def test_provider_wall_clock_watchdog_stops_drip_response(monkeypatch, tmp_path: Path) -> None:
    class DripStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(20):
                time.sleep(0.02)
                yield b" "

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=DripStream())

    monkeypatch.setattr("api.provider.CALL_DEADLINE_SECONDS", 0.05)
    provider = AnthropicProvider(ProviderSettings(
        api_key="controlled", workspace_id=None, spend_cap_usd=1,
        accounting_path=tmp_path / "ledger.json",
    ), client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))
    started = monotonic()
    with pytest.raises(ProviderCallError, match="wall-clock") as caught:
        provider.generate(
            prompt_text="controlled",
            image_media_type="image/jpeg",
            image_base64=CONTROLLED_IMAGE_BASE64,
            output_schema=_output_schema(),
            deadline_at=monotonic() + 5,
        )
    assert caught.value.code == "timeout"
    assert monotonic() - started < 0.5


def test_live_api_rejects_extra_browser_authority_and_disabled_server_is_typed(client) -> None:
    config = client.get("/api/live-bedroom/config")
    assert config.status_code == 200
    assert "privateStyleId" not in config.text
    rejected = client.post("/api/live-bedroom/generate", json={
        "roomType": "bedroom", "referenceId": "ref-01", "coordinates": [0, 0, 0],
    })
    assert rejected.status_code == 422

    disabled = client.post("/api/live-bedroom/generate", json={"roomType": "bedroom", "referenceId": "ref-01"})
    assert disabled.status_code == 200
    assert disabled.json()["code"] == "configuration-error"
    assert disabled.json()["providerCalls"] == 0
