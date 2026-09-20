from __future__ import annotations

import base64
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
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
RUG = "rug-ravenna-prospect-moroccan"
CONTROLLED_IMAGE_BASE64 = base64.b64encode(Path("public/style-references/ref-02.jpg").read_bytes()).decode("ascii")


def selection(*intents: dict) -> dict:
    return {"intents": list(intents)}


def bed_intent(*, wall: str = "wall-north") -> dict:
    return {"id": "anchor-bed", "kind": "against", "productId": BED, "wallId": wall, "face": "back"}


def rug_intent(*, zone: str = "zone-f1237d317578") -> dict:
    return {"id": "rug-main", "kind": "in_zone", "productId": RUG, "zoneId": zone}


def blocked_bed_rug_selection() -> dict:
    return selection(bed_intent(), rug_intent(zone="zone-418b5e9c7f7d"))


def solved_bed_rug_selection() -> dict:
    return selection(bed_intent(), rug_intent())


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
        "FURNITUREOS_GENERATION_SPEND_MODE",
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


def test_live_generation_rejects_fuller_selection_outside_bed_optional_rug_stage() -> None:
    fuller = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "nightstand-right", "kind": "adjacent_to",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.7,
        },
        {
            "id": "dresser-main", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-east", "face": "back",
        },
        {
            "id": "rug-main", "kind": "in_zone",
            "productId": "rug-ravenna-prospect-moroccan",
            "zoneId": "zone-f1237d317578",
        },
    )
    provider = TranscriptProvider([fuller, fuller, fuller])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )

    assert result.status == "failed"
    assert result.code == "selection-correction-exhausted"
    assert result.providerCalls == 3
    assert [item.code for item in result.selectionRejections] == [
        "selection-scope-error",
        "selection-scope-error",
        "selection-scope-error",
    ]
    assert result.designFailure is None


@pytest.mark.parametrize(
    ("reference_id", "bed_product_id"),
    [
        ("ref-01", "bed-rivet-jonathan-queen-walnut"),
        ("ref-06", "bed-prudence-tufted-queen-natural"),
    ],
)
@pytest.mark.parametrize("include_rug", [False, True])
def test_live_generation_accepts_exact_bed_optional_rug_scope_for_approved_photos(
    reference_id: str,
    bed_product_id: str,
    include_rug: bool,
) -> None:
    intents = [{
        "id": "anchor-bed", "kind": "against", "productId": bed_product_id,
        "wallId": "wall-north", "face": "back",
    }]
    if include_rug:
        intents.append({
            "id": "rug-main", "kind": "in_zone", "productId": RUG,
            "zoneId": "zone-f1237d317578",
        })
    provider = TranscriptProvider([selection(*intents)])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId=reference_id),
        provider=provider,
    )

    assert result.status == "solved"
    assert result.providerCalls == 1
    assert [product.category for product in result.design.products] == (
        ["bed", "rug"] if include_rug else ["bed"]
    )
    prompt = json.loads(provider.calls[0]["prompt_text"])
    assert prompt["rules"]["selectionScope"] == {
        "instruction": (
            "Do not return nightstands, dressers, wardrobes, chairs, lamps, another bed, or more than one rug. "
            "Repairs must not add or remove a request."
        ),
        "maximumRequests": 2,
        "optional": {"category": "rug", "maximumCount": 1, "minimumCount": 0},
        "otherCategories": "forbidden",
        "required": {"category": "bed", "count": 1, "requestId": "anchor-bed"},
        "version": "bed-plus-optional-rug-v1",
    }
    assert {product["category"] for product in prompt["eligibleCatalogue"]} <= {"bed", "rug"}


def test_live_selection_scope_rejects_second_rug_without_silent_filtering() -> None:
    too_many = selection(
        bed_intent(),
        {"id": "rug-one", "kind": "in_zone", "productId": RUG, "zoneId": "zone-f1237d317578"},
        {"id": "rug-two", "kind": "in_zone", "productId": RUG, "zoneId": "zone-418b5e9c7f7d"},
    )
    provider = TranscriptProvider([too_many, too_many, too_many])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )

    assert result.status == "failed"
    assert result.code == "selection-correction-exhausted"
    assert result.providerCalls == 3
    assert [item.code for item in result.selectionRejections] == ["selection-scope-error"] * 3
    assert result.designFailure is None


def test_repair_cannot_expand_bed_only_identity_with_optional_rug() -> None:
    invalid_initial = selection({**bed_intent(), "kind": "centred_on"})
    expanded_repair = selection(
        bed_intent(),
        {"id": "rug-main", "kind": "in_zone", "productId": RUG, "zoneId": "zone-f1237d317578"},
    )
    provider = TranscriptProvider([invalid_initial, expanded_repair, selection(bed_intent())])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )

    assert result.status == "solved"
    assert result.providerCalls == 3
    assert [item.code for item in result.selectionRejections] == ["repair-identity-error"]
    assert [attempt.outcome for attempt in result.design.arrangementHistory.attempts] == [
        "placement-failed", "solved",
    ]
    assert [placement.instanceId for placement in result.design.placements] == ["anchor-bed"]


@pytest.mark.parametrize(
    ("reference_id", "product_id", "witnessed_option"),
    [
        ("ref-01", "bed-alkove-hayes-double-wild-oak", ("against", "wall-north", "back", None)),
        ("ref-06", "bed-prudence-tufted-queen-natural", ("against", "wall-north", "back", None)),
    ],
)
def test_authoritative_bed_guidance_precedes_provider_and_labels_bed_only_scope(
    reference_id: str,
    product_id: str,
    witnessed_option: tuple[str, str, str, None],
) -> None:
    provider = TranscriptProvider([selection(bed_intent())])
    generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId=reference_id),
        provider=provider,
    )

    prompt = json.loads(provider.calls[0]["prompt_text"])
    guidance = prompt["placementGuidance"]
    assert guidance["method"] == "authoritative-bed-only-v1"
    assert guidance["scope"] == "A witnessed bed option is not a complete furnished Design guarantee."
    assert guidance["probesExecuted"] <= guidance["maxProbes"]
    options = guidance["bedWallOptionsByProduct"][product_id]
    assert [*witnessed_option, "witnessed-valid"] in options
    assert {row[-1] for rows in guidance["bedWallOptionsByProduct"].values() for row in rows} <= {
        "witnessed-valid", "conclusively-invalid", "unknown-bounded-search",
    }


def test_captured_fuller_draft_is_now_rejected_by_the_live_stage_scope() -> None:
    initial = selection(
        {
            "id": "anchor-bed", "kind": "centred_on",
            "productId": "bed-alkove-hayes-double-wild-oak",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "nightstand-left", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "left", "gapM": 0.06,
        },
        {
            "id": "nightstand-right", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.06,
        },
    )
    repaired = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-alkove-hayes-double-wild-oak",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "nightstand-left", "kind": "against",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "wallId": "wall-east", "face": "back",
        },
        {
            "id": "nightstand-right", "kind": "against",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "wallId": "wall-east", "face": "back",
        },
    )
    provider = TranscriptProvider([initial, repaired, repaired])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )

    assert result.status == "failed"
    assert result.designFailure is None
    assert [item.code for item in result.selectionRejections] == [
        "selection-scope-error", "selection-scope-error", "selection-scope-error",
    ]


def test_captured_fuller_smoke_never_crosses_the_live_arrangement_boundary() -> None:
    malformed = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "req-nightstand-right", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
        {
            "id": "req-dresser", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "req-rug", "kind": "in_zone",
            "productId": "rug-ravenna-prospect-moroccan",
            "zoneId": "zone-f1237d317578",
        },
    )
    first_graph_valid = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "req-nightstand-right", "kind": "adjacent_to",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
        {
            "id": "req-dresser", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "req-rug", "kind": "in_zone",
            "productId": "rug-ravenna-prospect-moroccan",
            "zoneId": "zone-f1237d317578",
        },
    )
    witnessed_correction = deepcopy(first_graph_valid)
    witnessed_correction["intents"][1]["gapM"] = 0.7
    witnessed_correction["intents"][2]["wallId"] = "wall-east"
    provider = TranscriptProvider([malformed, first_graph_valid, witnessed_correction])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
        generation_id_factory=lambda: "generation-fix-8-regression",
    )

    assert result.status == "failed"
    assert result.providerCalls == 3
    assert result.designFailure is None
    assert [item.code for item in result.selectionRejections] == [
        "graph-error", "selection-scope-error", "selection-scope-error",
    ]


def test_actual_h10_fuller_draft_is_rejected_before_transport_failure() -> None:
    initial = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-alkove-hayes-double-wild-oak",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "nightstand-left", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "left", "gapM": 0.6,
        },
        {
            "id": "nightstand-right", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
        {
            "id": "dresser-west-wall", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "rug-foot-of-bed", "kind": "in_zone",
            "productId": "rug-stone-beam-jute-natural",
            "zoneId": "zone-f1237d317578",
        },
    )
    provider = TranscriptProvider([
        initial,
        ProviderCallError("transport-error", "Controlled stop after correction capture.", attempted=False),
    ])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
        generation_id_factory=lambda: "generation-h10-exact-red-green",
    )

    assert result.status == "failed"
    assert result.code == "transport-error"
    assert result.providerCalls == 2
    assert result.designFailure is None
    assert [item.code for item in result.selectionRejections] == ["selection-scope-error"]
    correction_prompt = json.loads(provider.calls[1]["prompt_text"])
    assert correction_prompt["validSelectionNumber"] == 0
    assert correction_prompt["chronologicalHistory"] is None


def test_actual_h10_five_item_drafts_do_not_unlock_existing_drop_policy() -> None:
    initial = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-alkove-hayes-double-wild-oak",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "nightstand-left", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "left", "gapM": 0.6,
        },
        {
            "id": "nightstand-right", "kind": "flanking",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
        {
            "id": "dresser-west-wall", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "rug-foot-of-bed", "kind": "in_zone",
            "productId": "rug-stone-beam-jute-natural",
            "zoneId": "zone-f1237d317578",
        },
    )
    guided_repair = deepcopy(initial)
    guided_repair["intents"][0]["wallId"] = "wall-south"
    provider = TranscriptProvider([initial, guided_repair, deepcopy(guided_repair)])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
        generation_id_factory=lambda: "generation-h10-five-item-drop-boundary",
    )

    assert result.providerCalls == 3
    assert result.status == "failed"
    assert result.designFailure is None
    assert [item.code for item in result.selectionRejections] == [
        "selection-scope-error", "selection-scope-error", "selection-scope-error",
    ]


def test_composition_alternatives_preserve_identity_and_atomic_flanking_closure() -> None:
    room = intent_fixture_room()
    zone_offer = live_generation.derive_zones(room)
    reference = next(item for item in reference_manifest().images if item.id == "ref-01")
    eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
    capabilities = live_generation._wall_capability_map(room, eligible)
    payload = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "nightstand-left", "kind": "flanking",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "anchor-bed", "side": "left", "gapM": 0.6,
        },
        {
            "id": "nightstand-right", "kind": "flanking",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
    )
    selected = live_generation._validated_selection(
        payload,
        eligible,
        room=room,
        zone_offer=zone_offer,
        capabilities=capabilities,
        selection_id="initial",
        initial=None,
    )

    alternatives = live_generation._composition_alternatives(
        selected, eligible, capabilities, zone_offer,
    )
    anchor_alternatives = [
        alternative for alternative in alternatives
        if alternative.request_ids == ("anchor-bed",)
    ]
    flanking = [
        alternative
        for alternative in alternatives
        if any(intent.kind == "flanking" for intent in alternative.replacements)
    ]

    assert anchor_alternatives
    assert {alternative.replacements[0].wallId for alternative in anchor_alternatives} >= {
        "wall-east", "wall-south", "wall-west",
    }
    for alternative in anchor_alternatives:
        assert alternative.replacements[0].productId == "bed-rivet-jonathan-queen-walnut"
        scope = live_generation._pair_scope(selected.intents, alternative.replacements)
        assert [intent.id for intent in scope] == [
            "anchor-bed", "nightstand-left", "nightstand-right",
        ]

    assert flanking
    original_products = {intent.id: intent.productId for intent in selected.intents}
    for alternative in flanking:
        assert alternative.request_ids == ("nightstand-left", "nightstand-right")
        assert {intent.side for intent in alternative.replacements} == {"left", "right"}
        assert len({intent.gapM for intent in alternative.replacements}) == 1
        assert all(intent.productId == original_products[intent.id] for intent in alternative.replacements)
        pair = live_generation._pair_scope(selected.intents, alternative.replacements)
        assert {intent.id for intent in pair} == {
            "anchor-bed", "nightstand-left", "nightstand-right",
        }

    provider_schema = json.dumps(_output_schema(), sort_keys=True)
    assert "exactly two distinct requests" in provider_schema
    assert "same referenceId and gapM" in provider_schema


def test_composition_guidance_checks_downstream_atomic_group_before_emitting_witness() -> None:
    payload = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "storage", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "storage-left", "kind": "flanking",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "storage", "side": "left", "gapM": 0.6,
        },
        {
            "id": "storage-right", "kind": "flanking",
            "productId": "nightstand-hallowood-waverly-light-oak",
            "referenceId": "storage", "side": "right", "gapM": 0.6,
        },
    )
    original_payload = deepcopy(payload)
    room = intent_fixture_room()
    zone_offer = live_generation.derive_zones(room)
    reference = next(item for item in reference_manifest().images if item.id == "ref-01")
    eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
    capabilities = live_generation._wall_capability_map(room, eligible)
    selected = live_generation._validated_selection(
        payload,
        eligible,
        room=room,
        zone_offer=zone_offer,
        capabilities=capabilities,
        selection_id="initial",
        initial=None,
    )
    guide = live_generation._composition_correction_guidance(
        catalogue, room, zone_offer, eligible, capabilities, selected,
    )
    incomplete_east_witnesses = [
        witness
        for witness in guide["pairWitnesses"]
        if witness["requestIds"] == ["storage"]
        and witness["replacementIntents"][0].get("wallId") == "wall-east"
    ]
    assert incomplete_east_witnesses == []
    alternative = next(
        item
        for item in live_generation._composition_alternatives(
            selected, eligible, capabilities, zone_offer,
        )
        if item.request_ids == ("storage",) and item.replacements[0].wallId == "wall-east"
    )
    scope = live_generation._pair_scope(selected.intents, alternative.replacements)
    assert [intent.id for intent in scope] == [
        "anchor-bed", "storage", "storage-left", "storage-right",
    ]
    assert payload == original_payload
    assert guide["probesExecuted"] <= guide["maxProbes"] == 32
    assert guide["pairProbes"] + guide["completeDesignProbes"] == guide["probesExecuted"]


def test_pair_scope_follows_transitive_dependents_without_sweeping_unrelated_anchor_children() -> None:
    room = intent_fixture_room()
    zone_offer = live_generation.derive_zones(room)
    reference = next(item for item in reference_manifest().images if item.id == "ref-01")
    eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
    capabilities = live_generation._wall_capability_map(room, eligible)
    payload = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "anchor-child", "kind": "adjacent_to",
            "productId": "chair-rivet-slade-swivel-graphite",
            "referenceId": "anchor-bed", "side": "left", "gapM": 0.6,
        },
        {
            "id": "storage", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "storage-left", "kind": "flanking",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "storage", "side": "left", "gapM": 0.6,
        },
        {
            "id": "storage-right", "kind": "flanking",
            "productId": "nightstand-hallowood-waverly-light-oak",
            "referenceId": "storage", "side": "right", "gapM": 0.6,
        },
        {
            "id": "storage-left-child", "kind": "adjacent_to",
            "productId": "lamp-rivet-harper-brass",
            "referenceId": "storage-left", "side": "front", "gapM": 0.2,
        },
    )
    selected = live_generation._validated_selection(
        payload,
        eligible,
        room=room,
        zone_offer=zone_offer,
        capabilities=capabilities,
        selection_id="initial",
        initial=None,
    )
    before = selected.model_dump(mode="json")
    alternative = next(
        item
        for item in live_generation._composition_alternatives(
            selected, eligible, capabilities, zone_offer,
        )
        if item.request_ids == ("storage",) and item.replacements[0].wallId == "wall-east"
    )

    scope = live_generation._pair_scope(selected.intents, alternative.replacements)

    assert [intent.id for intent in scope] == [
        "anchor-bed", "storage", "storage-left", "storage-right", "storage-left-child",
    ]
    assert "anchor-child" not in {intent.id for intent in scope}
    original_products = {intent.id: intent.productId for intent in selected.intents}
    assert all(intent.productId == original_products[intent.id] for intent in scope)
    assert selected.model_dump(mode="json") == before


def test_composition_correction_shares_one_hard_probe_budget_and_does_not_promote_pair_only(
    monkeypatch,
) -> None:
    monkeypatch.setattr(live_generation, "MAX_COMPOSITION_GUIDANCE_PROBES", 1)
    failed_selection = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "req-nightstand-right", "kind": "adjacent_to",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
        {
            "id": "req-dresser", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-west", "face": "back",
        },
        {
            "id": "req-rug", "kind": "in_zone",
            "productId": "rug-ravenna-prospect-moroccan",
            "zoneId": "zone-f1237d317578",
        },
    )
    room = intent_fixture_room()
    zone_offer = live_generation.derive_zones(room)
    reference = next(item for item in reference_manifest().images if item.id == "ref-01")
    eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
    capabilities = live_generation._wall_capability_map(room, eligible)
    selected = live_generation._validated_selection(
        failed_selection, eligible, room=room, zone_offer=zone_offer,
        capabilities=capabilities, selection_id="initial", initial=None,
    )
    guide = live_generation._composition_correction_guidance(
        catalogue, room, zone_offer, eligible, capabilities, selected, max_probes=1,
    )
    assert guide["maxProbes"] == 1
    assert guide["probesExecuted"] == 1
    assert guide["pairProbes"] == 1
    assert guide["completeDesignProbes"] == 0
    assert guide["budgetExhausted"] is True
    assert guide["pairWitnesses"][0]["status"] == "pair-only-witnessed-valid"
    assert guide["completeDesignWitness"] is None


def test_composition_correction_reports_budget_exhausted_unknown_without_false_invalid(
    monkeypatch,
) -> None:
    monkeypatch.setattr(live_generation, "MAX_COMPOSITION_GUIDANCE_PROBES", 1)
    failed_selection = selection(
        {
            "id": "anchor-bed", "kind": "against",
            "productId": "bed-rivet-jonathan-queen-walnut",
            "wallId": "wall-north", "face": "back",
        },
        {
            "id": "req-nightstand-right", "kind": "adjacent_to",
            "productId": "nightstand-movian-havel-grey-white",
            "referenceId": "anchor-bed", "side": "right", "gapM": 0.6,
        },
        {
            "id": "req-dresser", "kind": "against",
            "productId": "dresser-stone-beam-brecken-brown",
            "wallId": "wall-east", "face": "back",
        },
        {
            "id": "req-rug", "kind": "in_zone",
            "productId": "rug-ravenna-prospect-moroccan",
            "zoneId": "zone-f1237d317578",
        },
    )
    room = intent_fixture_room()
    zone_offer = live_generation.derive_zones(room)
    reference = next(item for item in reference_manifest().images if item.id == "ref-01")
    eligible = catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
    capabilities = live_generation._wall_capability_map(room, eligible)
    selected = live_generation._validated_selection(
        failed_selection, eligible, room=room, zone_offer=zone_offer,
        capabilities=capabilities, selection_id="initial", initial=None,
    )
    guide = live_generation._composition_correction_guidance(
        catalogue, room, zone_offer, eligible, capabilities, selected, max_probes=1,
    )
    assert guide["probesExecuted"] == guide["maxProbes"] == 1
    assert guide["budgetExhausted"] is True
    assert guide["unknownProbes"] == 1
    assert guide["pairWitnesses"] == []
    assert guide["completeDesignWitness"] is None
    assert "invalid" not in json.dumps(guide).lower()


def test_failed_repair_retains_history_and_unknown_usage_without_drops() -> None:
    initial = blocked_bed_rug_selection()
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
    assert [item["id"] for item in repair_prompt["previousSelection"]["intents"]] == ["anchor-bed", "rug-main"]
    assert repair_prompt["previousSelection"]["intents"][1]["productId"] == RUG
    assert repair_prompt["actualPrecedingFeedback"]["outcome"] == "placement-failed"
    assert len(repair_prompt["chronologicalHistory"]) == 1


def test_valid_repair_uses_actual_feedback_and_does_not_replay_initial() -> None:
    initial = blocked_bed_rug_selection()
    repaired = solved_bed_rug_selection()
    provider = TranscriptProvider([initial, repaired])
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )
    assert result.status == "solved"
    assert result.providerCalls == 2
    assert [attempt.stage for attempt in result.design.arrangementHistory.attempts] == ["initial", "repair"]
    assert result.design.arrangementHistory.attempts[1].changedRequestIds == ("rug-main",)
    assert result.design.arrangementHistory.totalAttemptedCandidates <= 2 * 256


@pytest.mark.parametrize("reference_id", ["ref-01", "ref-06"])
def test_required_bed_spatial_repair_keeps_identity_and_recovers(reference_id: str) -> None:
    initial = selection({
        **bed_intent(),
        "kind": "centred_on",
    })
    repaired = selection(bed_intent())
    provider = TranscriptProvider([initial, repaired])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId=reference_id),
        provider=provider,
    )

    assert result.status == "solved"
    assert result.providerCalls == 2
    assert [attempt.outcome for attempt in result.design.arrangementHistory.attempts] == [
        "placement-failed", "solved",
    ]
    assert result.design.arrangementHistory.attempts[1].changedRequestIds == ("anchor-bed",)
    assert [placement.instanceId for placement in result.design.placements] == ["anchor-bed"]
    assert [placement.productId for placement in result.design.placements] == [BED]
    assert result.design.circulation.status == "clear"
    repair_prompt = json.loads(provider.calls[1]["prompt_text"])
    assert repair_prompt["immutableRepairContract"]["requiredBed"] == {
        "id": "anchor-bed", "productId": BED,
    }
    assert repair_prompt["immutableRepairContract"]["bedSpatialIntentMayChange"] is True


def test_two_product_repair_solves_without_optional_drop() -> None:
    initial = blocked_bed_rug_selection()
    repaired = solved_bed_rug_selection()

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([initial, repaired]),
    )

    assert result.status == "solved"
    assert result.providerCalls == 2
    assert [placement.instanceId for placement in result.design.placements] == [
        "anchor-bed", "rug-main",
    ]
    assert [attempt.stage for attempt in result.design.arrangementHistory.attempts] == [
        "initial", "repair",
    ]
    assert all(attempt.stage != "drop" for attempt in result.design.arrangementHistory.attempts)


@pytest.mark.parametrize("outcomes", [
    [selection(bed_intent())],
    [blocked_bed_rug_selection(), solved_bed_rug_selection()],
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
    assert any(item.id == "zone-418b5e9c7f7d" for item in offered.zones)
    assert any(item.id == "zone-f1237d317578" for item in offered.zones)
    initial = blocked_bed_rug_selection()
    repair = solved_bed_rug_selection()
    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([initial, repair]),
    )
    assert result.status == "solved"
    assert result.providerCalls == 2
    assert calls == {"live": 1, "arrangement": 0, "domain": 0}


def test_optional_drop_waits_until_two_valid_repairs_are_exhausted() -> None:
    blocked = blocked_bed_rug_selection()
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
    assert result.design.arrangementHistory.attempts[-1].droppedRequestIds == ("rug-main",)
    assert len(result.design.arrangementHistory.attempts) <= 23


def test_invalid_repair_category_terminates_without_optional_drop() -> None:
    initial = blocked_bed_rug_selection()
    changed_category = selection(
        bed_intent(),
        {"id": "rug-main", "kind": "against", "productId": "nightstand-alkove-hayes-wild-oak", "wallId": "wall-east", "face": "back"},
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
    initial = blocked_bed_rug_selection()
    invalid_repair = selection(
        bed_intent(),
        {"id": "rug-main", "kind": "against", "productId": "nightstand-alkove-hayes-wild-oak", "wallId": "wall-east", "face": "back"},
    )
    valid_repair = solved_bed_rug_selection()
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
    blocked = blocked_bed_rug_selection()
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
        selection(bed_intent(), {**rug_intent(), "id": "renamed"}),
        "repair-identity-error",
    ),
    (
        selection({**bed_intent(), "productId": "bed-rivet-jonathan-queen-walnut"}, rug_intent()),
        "repair-anchor-error",
    ),
    (
        selection(
            bed_intent(),
            {"id": "rug-main", "kind": "against", "productId": "nightstand-alkove-hayes-wild-oak", "wallId": "wall-east", "face": "back"},
        ),
        "repair-category-error",
    ),
])
def test_invalid_repairs_report_typed_immutable_contract_errors(invalid_repair: dict, expected_code: str) -> None:
    initial = blocked_bed_rug_selection()
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
        eligible = live_generation._live_selection_products(
            catalogue.list(CatalogueQuery(room_type="bedroom", private_style_id=reference.privateStyleId))
        )
        capabilities = live_generation._wall_capability_map(room, eligible)
        prompt = live_generation._prompt(
            eligible=eligible,
            room=room,
            zone_offer=zone_offer,
            capabilities=capabilities,
            bed_guidance=live_generation._bed_placement_guidance(
                catalogue, room, zone_offer, eligible, capabilities,
            ),
            provider_call_index=0,
            previous=None,
            session=None,
        )
        initial_sizes[reference.id] = len(prompt.encode("utf-8"))
    assert set(initial_sizes) == {f"ref-0{index}" for index in range(1, 7)}
    assert max(initial_sizes.values()) <= live_generation.MAX_PROMPT_TEXT_BYTES

    blocked = blocked_bed_rug_selection()
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
    repaired = solved_bed_rug_selection()
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


def test_frozen_generation_configuration_binds_composition_and_flanking_contract() -> None:
    configuration = live_generation.frozen_generation_configuration(catalogue)

    assert configuration["version"] == "ticket-6-generation-config-v9"
    assert configuration["provider"]["selectionGrammar"] == (
        "strict-anyOf-v6-bed-plus-optional-rug"
    )
    assert configuration["provider"]["selectionScope"] == {
        "version": "bed-plus-optional-rug-v1",
        "requiredBedCount": 1,
        "optionalRugMinimumCount": 0,
        "optionalRugMaximumCount": 1,
        "maximumRequests": 2,
        "allowedCategories": ["bed", "rug"],
        "enforcedOn": ["initial", "repair"],
        "silentFiltering": False,
    }
    assert configuration["provider"]["compositionGuidance"] == {
        "diagnosticScope": "changed-anchor-or-request-transitive-dependents-atomic-flanking-and-ancestors-v3",
        "repairBedGuidance": "selected-anchor-product-only",
        "maxAuthorityProbesPerFailedSelection": 32,
        "maxPairProbes": 16,
        "maxPairWitnesses": 8,
        "maxBytes": 8192,
        "gapStepM": 0.1,
        "gapStepMultipliers": [1, 2, 4],
    }
    assert max(configuration["promptContractBytesByReference"].values()) <= (
        live_generation.MAX_PROMPT_TEXT_BYTES
    )


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

    protected_initial = ArrangementSelection.model_validate({
        "id": "initial",
        "intents": [{**bed_intent(), "kind": "centred_on"}],
    })
    legacy_incremental = ArrangementRequest.model_validate({
        **request.model_dump(mode="json"),
        "selections": [protected_initial.model_dump(mode="json")],
    })
    protected_session = ArrangementSession(catalogue, legacy_incremental, selection_limit=3)
    assert protected_session.submit(protected_initial) is None
    changed_anchor = ArrangementSelection.model_validate({
        "id": "repair-1", "intents": [bed_intent()],
    })
    with pytest.raises(ValidationError, match="may not change required or anchor"):
        protected_session.submit(changed_anchor)


def test_repositionable_policy_is_explicit_and_excludes_bed_from_immovable_attribution(monkeypatch) -> None:
    initial = ArrangementSelection.model_validate({"id": "initial", "intents": [bed_intent()]})
    request = ArrangementRequest.model_validate({
        "room": intent_fixture_room().model_dump(mode="json"),
        "selections": [initial.model_dump(mode="json")],
        "policies": [{"requestId": "anchor-bed", "required": True, "anchor": True}],
        "clearanceWidthM": 0.6,
        "maxCandidates": 256,
    })
    seen_anchor_ids = []
    actual_validate = arrangement_module.validate_circulation

    def capture_anchor_ids(*args, **kwargs):
        seen_anchor_ids.append(kwargs["anchor_ids"])
        return actual_validate(*args, **kwargs)

    monkeypatch.setattr(arrangement_module, "validate_circulation", capture_anchor_ids)
    session = ArrangementSession(
        catalogue,
        request,
        selection_limit=3,
        repositionable_request_ids=frozenset({"anchor-bed"}),
    )
    assert session.submit(initial) is not None
    assert seen_anchor_ids == [frozenset()]

    with pytest.raises(ValueError, match="only required anchor"):
        ArrangementSession(
            catalogue,
            request,
            repositionable_request_ids=frozenset({"not-a-policy-request"}),
        )


def test_repositionable_context_preserves_every_arrangement_request_invariant() -> None:
    initial_bed = {**bed_intent(), "kind": "centred_on"}
    required_storage = {
        "id": "required-storage",
        "kind": "against",
        "productId": "wardrobe-movian-cinca-five-door",
        "wallId": "wall-east",
        "face": "back",
    }
    body = {
        "room": intent_fixture_room().model_dump(mode="json"),
        "selections": [
            {"id": "initial", "intents": [initial_bed, required_storage]},
            {"id": "repair-1", "intents": [bed_intent(), required_storage]},
        ],
        "policies": [
            {"requestId": "anchor-bed", "required": True, "anchor": True},
            {"requestId": "required-storage", "required": True, "anchor": False},
        ],
        "clearanceWidthM": 0.6,
        "maxCandidates": 256,
    }
    context = {"repositionable_request_ids": frozenset({"anchor-bed"})}
    assert ArrangementRequest.model_validate(body, context=context).selections[1].intents[0].kind == "against"

    cases = []
    duplicate_selection = json.loads(json.dumps(body))
    duplicate_selection["selections"][1]["id"] = "initial"
    cases.append((duplicate_selection, "selection IDs must be unique", context))

    duplicate_request = json.loads(json.dumps(body))
    duplicate_request["selections"][1]["intents"][1]["id"] = "anchor-bed"
    cases.append((duplicate_request, "preserve the initial request identity", context))

    missing_request = json.loads(json.dumps(body))
    missing_request["selections"][1]["intents"].pop()
    cases.append((missing_request, "preserve the initial request identity", context))

    changed_other_required = json.loads(json.dumps(body))
    changed_other_required["selections"][1]["intents"][1]["wallId"] = "wall-south"
    cases.append((changed_other_required, "may not change required or anchor", context))

    changed_bed_product = json.loads(json.dumps(body))
    changed_bed_product["selections"][1]["intents"][0]["productId"] = "bed-rivet-jonathan-queen-walnut"
    cases.append((changed_bed_product, "must preserve Product identity", context))

    duplicate_policy = json.loads(json.dumps(body))
    duplicate_policy["policies"][1]["requestId"] = "anchor-bed"
    cases.append((duplicate_policy, "policy request IDs must be unique", context))

    uncovered_initial = json.loads(json.dumps(body))
    uncovered_initial["policies"].pop()
    cases.append((uncovered_initial, "cover every initial request", context))

    for invalid, message, validation_context in cases:
        with pytest.raises(ValidationError, match=message):
            ArrangementRequest.model_validate(invalid, context=validation_context)

    with pytest.raises(ValidationError, match="only required anchor"):
        ArrangementRequest.model_validate(
            body,
            context={"repositionable_request_ids": frozenset({"required-storage"})},
        )


def test_live_grid_feedback_retains_observed_scoped_placement_rejection() -> None:
    provider = TranscriptProvider([blocked_bed_rug_selection(), solved_bed_rug_selection()])

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=provider,
    )

    assert result.status == "solved"
    feedback = json.loads(provider.calls[1]["prompt_text"])["actualPrecedingFeedback"]
    assert feedback["outcome"] == "placement-failed"
    assert feedback["attemptedCandidates"] == 25
    assert feedback["limitingConstraint"]["code"] in {
        "search-exhausted", "outside-zone", "collision", "access-region-blocked",
    }


def test_fuller_required_dependency_is_rejected_before_arrangement_drop_policy() -> None:
    dependent_bed = {
        "id": "anchor-bed",
        "kind": "adjacent_to",
        "productId": BED,
        "referenceId": "nightstand",
        "side": "right",
        "gapM": 0,
    }
    nightstand = {
        "id": "nightstand",
        "kind": "against",
        "productId": "nightstand-alkove-hayes-wild-oak",
        "wallId": "wall-east",
        "face": "back",
    }
    blocked = selection(dependent_bed, nightstand)

    result = generate_live_bedroom(
        catalogue,
        LiveGenerationRequest(roomType="bedroom", referenceId="ref-01"),
        provider=TranscriptProvider([blocked, blocked, blocked]),
    )

    assert result.status == "failed"
    assert result.providerCalls == 3
    assert result.designFailure is None
    assert [item.code for item in result.selectionRejections] == [
        "selection-scope-error", "selection-scope-error", "selection-scope-error",
    ]


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
    with pytest.raises(ProviderCallError, match="closed after usage exceeded"):
        ledger.reserve(1)

    uncapped_path = tmp_path / "uncapped-ledger.json"
    uncapped = BudgetLedger(uncapped_path, None, accounting_mode="uncapped")
    uncapped_reservation, _ = uncapped.reserve(1)
    with pytest.raises(ProviderCallError, match="exceeded"):
        uncapped.settle(
            uncapped_reservation,
            ProviderUsage(inputTokens=1_100_000, outputTokens=10_000, costUsd=8.0),
        )
    with pytest.raises(ProviderCallError, match="closed after usage exceeded"):
        uncapped.reserve(1)


def test_explicit_uncapped_settings_require_unambiguous_external_credentials(monkeypatch, tmp_path: Path) -> None:
    credential = tmp_path / "current.env.local"
    credential.write_text(
        "ANTHROPIC_API_KEY=current-controlled\nANTHROPIC_WORKSPACE_ID=current-workspace\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FURNITUREOS_LIVE_GENERATION_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_CREDENTIAL_FILE", str(credential))
    monkeypatch.setenv("FURNITUREOS_GENERATION_SPEND_MODE", "uncapped")
    monkeypatch.delenv("FURNITUREOS_GENERATION_SPEND_CAP_USD", raising=False)
    monkeypatch.setenv("FURNITUREOS_GENERATION_ACCOUNTING_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stale-controlled")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "stale-workspace")

    with pytest.raises(ProviderCallError, match="must not be combined"):
        ProviderSettings.from_environment()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID")
    settings = ProviderSettings.from_environment()
    assert settings.accounting_mode == "uncapped"
    assert settings.spend_cap_usd is None
    assert settings.api_key == "current-controlled"
    assert settings.workspace_id == "current-workspace"

    monkeypatch.setenv("FURNITUREOS_GENERATION_SPEND_CAP_USD", "5")
    with pytest.raises(ProviderCallError, match="must not include a numeric cap"):
        ProviderSettings.from_environment()


def test_uncapped_ledger_atomically_migrates_v1_history_and_keeps_recording(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    historical = {
        "version": 1,
        "capUsd": 10.0,
        "committedUsd": 7.41773,
        "reservations": [
            {"id": "known", "status": "settled", "maximumUsd": 0.6048, "actualUsd": 0.1},
            {"id": "unknown", "status": "reserved-unknown", "maximumUsd": 0.6048},
        ],
    }
    path.write_text(json.dumps(historical), encoding="utf-8")
    original_rows = deepcopy(historical["reservations"])
    ledger = BudgetLedger(path, None, accounting_mode="uncapped")

    reservation, maximum = ledger.reserve(10)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["version"] == 2
    assert state["accountingMode"] == "uncapped"
    assert state["capUsd"] is None
    assert state["migratedFrom"] == {"version": 1, "capUsd": 10.0}
    assert state["reservations"][:2] == original_rows
    assert state["committedUsd"] == pytest.approx(7.41773 + maximum)
    assert state["reservations"][-1]["status"] == "reserved-unknown"

    ledger.settle(reservation, ProviderUsage(inputTokens=10, outputTokens=2, costUsd=0.0001))
    settled = json.loads(path.read_text(encoding="utf-8"))
    assert settled["reservations"][:2] == original_rows
    assert settled["committedUsd"] == pytest.approx(7.41783)


def test_capped_and_uncapped_ledgers_remain_serialized_and_mode_bound(tmp_path: Path) -> None:
    capped_path = tmp_path / "capped.json"
    capped = BudgetLedger(capped_path, 2.0, accounting_mode="capped")
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(lambda _index: capped.reserve(1), range(2)))
    state = json.loads(capped_path.read_text(encoding="utf-8"))
    assert len(state["reservations"]) == len(reservations) == 2
    assert len({item[0] for item in reservations}) == 2
    with pytest.raises(ProviderCallError, match="mode"):
        BudgetLedger(capped_path, None, accounting_mode="uncapped").reserve(1)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text(json.dumps({
        "version": 2,
        "accountingMode": "uncapped",
        "capUsd": None,
        "committedUsd": -1,
        "reservations": [],
    }), encoding="utf-8")
    with pytest.raises(ProviderCallError, match="invalid"):
        BudgetLedger(malformed_path, None, accounting_mode="uncapped").reserve(1)

    malformed_row_path = tmp_path / "malformed-row.json"
    malformed_row_path.write_text(json.dumps({
        "version": 2,
        "accountingMode": "uncapped",
        "capUsd": None,
        "committedUsd": 0,
        "reservations": [{"id": "sentinel", "status": "invented", "maximumUsd": 1}],
    }), encoding="utf-8")
    with pytest.raises(ProviderCallError, match="reservation history"):
        BudgetLedger(malformed_row_path, None, accounting_mode="uncapped").reserve(1)


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
