"""Image-directed live bedroom generation with FastAPI-owned policy and geometry."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
from time import monotonic
from typing import Annotated, Any, Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator

from .arrangement import ArrangementSession, MAX_ARRANGEMENT_SOLVES, MAX_REPAIR_ATTEMPTS
from .catalogue.contract import Catalogue, CatalogueQuery
from .circulation import validate_circulation
from .design import intent_fixture_room
from .domain import SEARCH_STEP_M, WallPlacementCapability, resolve_design, wall_placement_capabilities
from .models import (
    ArrangementRequest,
    ArrangementSelection,
    DesignFailure,
    DesignRequest,
    PlacementIntent,
    PlacementPolicy,
    Product,
    ProductCategory,
    RoomShell,
    RoomType,
    SolvedDesign,
    ZoneOffer,
)
from .provider import (
    AnthropicProvider,
    CONSERVATIVE_INPUT_TOKEN_RESERVATION,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_EDGE_PX,
    MAX_IMAGE_SHORT_EDGE_PX,
    MAX_IMAGE_VISUAL_TOKENS,
    MODEL_ID,
    MAX_PROVIDER_SCHEMA_BYTES,
    MAX_PROMPT_TEXT_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SERIALIZED_REQUEST_BYTES,
    OVERALL_DEADLINE_SECONDS,
    ProviderCallError,
    ProviderReply,
    ProviderSettings,
    ProviderUsage,
    provider_configuration_available,
)
from .zones import derive_zones

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_MANIFEST = Path(__file__).with_name("live-reference-manifest.json")
REFERENCE_DIR = ROOT / "public" / "style-references"
CLEARANCE_WIDTH_M = 0.60
MAX_CANDIDATES = 256
MAX_BED_GUIDANCE_PROBES = 32
MAX_COMPOSITION_GUIDANCE_PROBES = 32
MAX_COMPOSITION_PAIR_PROBES = 16
MAX_COMPOSITION_PAIR_WITNESSES = 8
MAX_COMPOSITION_GUIDANCE_BYTES = 8_192
ANCHOR_ID = "anchor-bed"
LIVE_SELECTION_SCOPE_VERSION = "bed-plus-optional-rug-v1"
LIVE_SELECTION_CATEGORIES = frozenset({"bed", "rug"})
GenerationFailureCode = Literal[
    "configuration-error",
    "budget-error",
    "transport-error",
    "timeout",
    "rate-limit",
    "provider-error",
    "provider-schema-error",
    "selection-correction-exhausted",
    "eligible-catalogue-error",
    "no-valid-design",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceRecord(StrictModel):
    id: str = Field(pattern=r"^ref-0[1-6]$")
    privateStyleId: str = Field(pattern=r"^style-0[1-5]$")
    label: str = Field(min_length=1, max_length=80)
    creator: str = Field(min_length=1, max_length=100)
    sourceUrl: str = Field(pattern=r"^https://")
    license: str = Field(min_length=1)
    licenseUrl: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(gt=0, le=524_288)
    fileName: str = Field(pattern=r"^ref-0[1-6]\.jpg$")


class ReferenceManifest(StrictModel):
    version: Literal["ticket-6-reference-candidates-v1"]
    ownerApproval: Literal["pending", "approved"]
    scheduleApproval: Literal["pending", "approved"]
    images: tuple[ReferenceRecord, ...] = Field(min_length=6, max_length=6)
    proposedTenRunSchedule: tuple[str, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def stable_ids(self) -> "ReferenceManifest":
        ids = [image.id for image in self.images]
        if ids != [f"ref-0{index}" for index in range(1, 7)]:
            raise ValueError("reference ids must be the stable ordered set ref-01 through ref-06")
        if any(reference_id not in ids for reference_id in self.proposedTenRunSchedule):
            raise ValueError("the proposed schedule references an unknown image")
        return self


@lru_cache
def reference_manifest() -> ReferenceManifest:
    return ReferenceManifest.model_validate_json(REFERENCE_MANIFEST.read_text(encoding="utf-8"))


def verified_reference(record: ReferenceRecord) -> bytes:
    path = REFERENCE_DIR / record.fileName
    data = path.read_bytes()
    if len(data) != record.bytes or hashlib.sha256(data).hexdigest() != record.sha256:
        raise ProviderCallError("configuration-error", f'Reference image "{record.id}" failed its byte identity check.')
    return data


class PublicReference(StrictModel):
    id: str
    label: str
    imageUrl: str
    creator: str
    sourceUrl: str
    license: str
    licenseUrl: str
    sha256: str


class LiveBedroomConfig(StrictModel):
    roomType: Literal["bedroom"] = "bedroom"
    referenceSetVersion: str
    referenceApproval: Literal["pending", "approved"]
    scheduleApproval: Literal["pending", "approved"]
    references: tuple[PublicReference, ...]
    providerModel: Literal["claude-opus-5"] = MODEL_ID
    providerCapability: Literal["verified"] = "verified"
    realCallsEnabled: bool
    phoneGate: Literal["waived"] = "waived"


class LiveGenerationRequest(StrictModel):
    roomType: Literal["bedroom"]
    referenceId: str = Field(pattern=r"^ref-0[1-6]$")


IntentKind = Literal["against", "centred_on", "in_corner", "adjacent_to", "facing", "flanking", "in_zone"]
ProviderIntentId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
ProviderProductId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
ProviderWallId = Annotated[str, Field(min_length=1, max_length=64)]
ProviderZoneId = Annotated[str, Field(min_length=1, max_length=80)]
ProviderGap = Annotated[float, Field(ge=-1000, le=1000, allow_inf_nan=False)]


class ProviderIntentBase(StrictModel):
    id: ProviderIntentId
    productId: ProviderProductId


class ProviderAgainstIntent(ProviderIntentBase):
    kind: Literal["against"]
    wallId: ProviderWallId
    face: Literal["front", "back", "left", "right"]


class ProviderCentredIntent(ProviderIntentBase):
    kind: Literal["centred_on"]
    wallId: ProviderWallId
    face: Literal["front", "back", "left", "right"]


class ProviderCornerIntent(ProviderIntentBase):
    kind: Literal["in_corner"]
    wallId: ProviderWallId
    face: Literal["front", "back", "left", "right"]
    adjacentWallId: ProviderWallId


class ProviderAdjacentIntent(ProviderIntentBase):
    kind: Literal["adjacent_to"]
    referenceId: ProviderIntentId
    side: Literal["front", "back", "left", "right"]
    gapM: ProviderGap


class ProviderFacingIntent(ProviderIntentBase):
    kind: Literal["facing"]
    referenceId: ProviderIntentId
    gapM: ProviderGap


class ProviderFlankingIntent(ProviderIntentBase):
    kind: Literal["flanking"]
    referenceId: ProviderIntentId
    side: Literal["left", "right"]
    gapM: ProviderGap


class ProviderZoneIntent(ProviderIntentBase):
    kind: Literal["in_zone"]
    zoneId: ProviderZoneId


ProviderIntent = (
    ProviderAgainstIntent
    | ProviderCentredIntent
    | ProviderCornerIntent
    | ProviderAdjacentIntent
    | ProviderFacingIntent
    | ProviderFlankingIntent
    | ProviderZoneIntent
)


class ProviderSelection(StrictModel):
    intents: tuple[ProviderIntent, ...] = Field(
        min_length=1,
        max_length=20,
        description=(
            "For one lone related Product use adjacent_to. A flanking group is atomic: exactly two distinct "
            "requests with the same referenceId and gapM, one side left and one side right."
        ),
    )


SelectionRejectionCode = Literal[
    "operation-shape-error",
    "ineligible-product-error",
    "selection-scope-error",
    "anchor-error",
    "wall-face-error",
    "corner-face-error",
    "graph-error",
    "repair-identity-error",
    "repair-anchor-error",
    "repair-category-error",
]


class SelectionRejection(StrictModel):
    code: SelectionRejectionCode
    detail: str = Field(min_length=1, max_length=240)
    path: str | None = Field(default=None, max_length=160)
    intentId: str | None = Field(default=None, max_length=64)


class SelectionRejected(ValueError):
    def __init__(self, rejection: SelectionRejection) -> None:
        super().__init__(rejection.detail)
        self.rejection = rejection


SelectionRejectionHistory = Annotated[tuple[SelectionRejection, ...], Field(max_length=3)]


class UsageSummary(StrictModel):
    known: bool
    inputTokens: int | None = Field(default=None, ge=0)
    outputTokens: int | None = Field(default=None, ge=0)
    costUsd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class LiveGenerationSuccess(StrictModel):
    status: Literal["solved"]
    generationId: str
    referenceId: str
    providerModel: str
    providerCalls: int = Field(ge=1, le=3)
    modelLatencyMs: int = Field(ge=0, le=300_000)
    usage: UsageSummary
    selectionRejections: SelectionRejectionHistory = ()
    design: SolvedDesign


class LiveGenerationFailure(StrictModel):
    status: Literal["failed"]
    generationId: str
    referenceId: str
    code: GenerationFailureCode
    detail: str
    providerModel: str = MODEL_ID
    providerCalls: int = Field(ge=0, le=3)
    modelLatencyMs: int = Field(ge=0, le=300_000)
    usage: UsageSummary
    selectionRejections: SelectionRejectionHistory = ()
    designFailure: DesignFailure | None = None


LiveGenerationResultValue = Annotated[LiveGenerationSuccess | LiveGenerationFailure, Field(discriminator="status")]


class LiveGenerationResult(RootModel[LiveGenerationResultValue]):
    pass


class GenerationProvider(Protocol):
    def generate(
        self,
        *,
        prompt_text: str,
        image_media_type: Literal["image/jpeg"],
        image_base64: str,
        output_schema: dict[str, Any],
        deadline_at: float,
    ) -> ProviderReply: ...


def public_config() -> LiveBedroomConfig:
    manifest = reference_manifest()
    return LiveBedroomConfig(
        referenceSetVersion=manifest.version,
        referenceApproval=manifest.ownerApproval,
        scheduleApproval=manifest.scheduleApproval,
        references=tuple(PublicReference(
            id=record.id,
            label=record.label,
            imageUrl=f"/style-references/{record.fileName}",
            creator=record.creator,
            sourceUrl=record.sourceUrl,
            license=record.license,
            licenseUrl=record.licenseUrl,
            sha256=record.sha256,
        ) for record in manifest.images),
        realCallsEnabled=provider_configuration_available(),
    )


def _usage_summary(usages: list[ProviderUsage | None]) -> UsageSummary:
    if not usages or any(usage is None for usage in usages):
        return UsageSummary(known=False)
    known = [usage for usage in usages if usage is not None]
    return UsageSummary(
        known=True,
        inputTokens=sum(usage.inputTokens for usage in known),
        outputTokens=sum(usage.outputTokens for usage in known),
        costUsd=sum(usage.costUsd for usage in known),
    )


def _failure(
    generation_id: str,
    reference_id: str,
    code: GenerationFailureCode,
    detail: str,
    calls: int,
    latency_ms: int,
    usages: list[ProviderUsage | None],
    design_failure: DesignFailure | None = None,
    selection_rejections: tuple[SelectionRejection, ...] = (),
) -> LiveGenerationFailure:
    return LiveGenerationFailure(
        status="failed",
        generationId=generation_id,
        referenceId=reference_id,
        code=code,
        detail=detail,
        providerCalls=calls,
        modelLatencyMs=latency_ms,
        usage=_usage_summary(usages),
        selectionRejections=selection_rejections,
        designFailure=design_failure,
    )


_UNSUPPORTED_PROVIDER_SCHEMA_KEYS = {
    "minimum": "minimum is enforced by the server",
    "maximum": "maximum is enforced by the server",
    "exclusiveMinimum": "exclusive minimum is enforced by the server",
    "exclusiveMaximum": "exclusive maximum is enforced by the server",
    "minLength": "minimum length is enforced by the server",
    "maxLength": "maximum length is enforced by the server",
    "pattern": "format pattern is enforced by the server",
    "minItems": "minimum item count is enforced by the server",
    "maxItems": "maximum item count is enforced by the server",
}


def _provider_schema_projection(value: Any) -> Any:
    if isinstance(value, list):
        return [_provider_schema_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    projected: dict[str, Any] = {}
    notes: list[str] = []
    for key, item in value.items():
        note = _UNSUPPORTED_PROVIDER_SCHEMA_KEYS.get(key)
        if note:
            notes.append(note)
            continue
        projected[key] = _provider_schema_projection(item)
    if notes:
        existing = str(projected.get("description", "")).strip()
        projected["description"] = "; ".join(filter(None, [existing, *sorted(set(notes))])) + "."
    return projected


def _output_schema() -> dict[str, Any]:
    """Anthropic-compatible shape; Pydantic retains all omitted constraints."""
    return _provider_schema_projection(ProviderSelection.model_json_schema())


WallCapabilityMap = dict[str, tuple[WallPlacementCapability, ...]]


def _wall_capability_map(room: RoomShell, eligible: tuple[Product, ...]) -> WallCapabilityMap:
    return {product.id: wall_placement_capabilities(room, product) for product in eligible}


def _capability_prompt_rows(capabilities: tuple[WallPlacementCapability, ...]) -> list[list[str | None]]:
    return [[
        item.kind,
        item.wall_id,
        item.face,
        item.adjacent_wall_id,
        item.secondary_face,
    ] for item in capabilities]


def _guidance_status(
    source: Catalogue,
    room: RoomShell,
    zone_offer: ZoneOffer,
    intent: PlacementIntent,
    *,
    verify_circulation: bool,
    max_candidates: int,
    clearance_width_m: float,
) -> tuple[Literal["witnessed-valid", "conclusively-invalid", "unknown-bounded-search"], int]:
    """Classify one bed-only option through the ordinary physical authority."""
    result = resolve_design(
        source,
        DesignRequest(room=room, intents=(intent,), maxCandidates=max_candidates),
        zone_offer=zone_offer,
    )
    attempted = result.search.attemptedCandidates
    if result.status == "failed":
        return ("conclusively-invalid" if result.search.exhaustive else "unknown-bounded-search"), attempted
    if not verify_circulation:
        return "unknown-bounded-search", attempted
    circulation = validate_circulation(result, clearance_width_m, anchor_ids=frozenset())
    if circulation.status == "clear":
        return "witnessed-valid", attempted
    return ("conclusively-invalid" if circulation.exhaustive else "unknown-bounded-search"), attempted


@lru_cache(maxsize=32)
def _cached_bed_placement_guidance(
    source: Catalogue,
    source_version: str,
    room: RoomShell,
    zone_offer: ZoneOffer,
    eligible: tuple[Product, ...],
    capability_items: tuple[tuple[str, tuple[WallPlacementCapability, ...]], ...],
    max_candidates: int,
    clearance_width_m: float,
    max_probes: int,
) -> str:
    """Cache only against complete Room/Product/solver/clearance inputs."""
    del source_version  # Included in the immutable cache key.
    capabilities = dict(capability_items)
    by_product: dict[str, list[list[str | None]]] = {}
    probes = 0
    candidate_checks = 0
    for product in sorted((item for item in eligible if item.category == "bed"), key=lambda item: item.id):
        rows: list[list[str | None]] = []
        witnessed = False
        for option in capabilities[product.id]:
            status: str = "unknown-bounded-search"
            # The diagnosed failures use the eight wall positions. Corners stay
            # available but honestly unknown under this fixed preflight budget.
            if option.kind in {"against", "centred_on"} and probes < max_probes:
                intent = PlacementIntent(
                    id=ANCHOR_ID,
                    kind=option.kind,
                    productId=product.id,
                    wallId=option.wall_id,
                    face=option.face,
                )
                status, attempted = _guidance_status(
                    source,
                    room,
                    zone_offer,
                    intent,
                    verify_circulation=not witnessed,
                    max_candidates=max_candidates,
                    clearance_width_m=clearance_width_m,
                )
                probes += 1
                candidate_checks += attempted
                witnessed = witnessed or status == "witnessed-valid"
            rows.append([
                option.kind,
                option.wall_id,
                option.face,
                option.adjacent_wall_id,
                status,
            ])
        by_product[product.id] = rows
    value = {
        "method": "authoritative-bed-only-v1",
        "scope": "A witnessed bed option is not a complete furnished Design guarantee.",
        "maxProbes": max_probes,
        "probesExecuted": probes,
        "candidateChecks": candidate_checks,
        "bedWallOptionTuple": ["kind", "wallId", "face", "adjacentWallId", "status"],
        "bedWallOptionsByProduct": by_product,
    }
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _bed_placement_guidance(
    source: Catalogue,
    room: RoomShell,
    zone_offer: ZoneOffer,
    eligible: tuple[Product, ...],
    capabilities: WallCapabilityMap,
) -> dict[str, Any]:
    """Produce bounded coordinate-free bed guidance from the real authority."""
    capability_items = tuple(sorted(capabilities.items()))
    return json.loads(_cached_bed_placement_guidance(
        source,
        source.version,
        room,
        zone_offer,
        eligible,
        capability_items,
        MAX_CANDIDATES,
        CLEARANCE_WIDTH_M,
        MAX_BED_GUIDANCE_PROBES,
    ))


def _access_relationship_warnings(
    selection: ArrangementSelection | None,
    eligible: tuple[Product, ...],
) -> list[dict[str, Any]]:
    if selection is None:
        return []
    products = {product.id: product for product in eligible}
    intents = {intent.id: intent for intent in selection.intents}
    warnings: list[dict[str, Any]] = []
    for intent in sorted(selection.intents, key=lambda item: item.id):
        if intent.kind not in {"adjacent_to", "flanking"} or intent.referenceId is None or intent.side is None:
            continue
        reference = intents[intent.referenceId]
        minimum = max(
            (
                region.depthM
                for region in products[reference.productId].accessRegions
                if region.required and region.face == intent.side
            ),
            default=0.0,
        )
        if minimum > 0 and intent.gapM < minimum - 1e-9:
            warnings.append({
                "requestId": intent.id,
                "referenceId": intent.referenceId,
                "side": intent.side,
                "chosenGapM": intent.gapM,
                "minimumGapM": minimum,
            })
    return warnings


GuidanceStatus = Literal["witnessed-valid", "conclusively-invalid", "unknown-bounded-search"]


@dataclass(frozen=True)
class _CompositionAlternative:
    request_ids: tuple[str, ...]
    replacements: tuple[PlacementIntent, ...]


@dataclass
class _CompositionProbeBudget:
    max_probes: int
    probes_executed: int = 0
    pair_probes: int = 0
    complete_design_probes: int = 0
    candidate_checks: int = 0
    unknown_probes: int = 0

    @property
    def exhausted(self) -> bool:
        return self.probes_executed >= self.max_probes


def _probe_composition_intents(
    source: Catalogue,
    room: RoomShell,
    zone_offer: ZoneOffer,
    intents: tuple[PlacementIntent, ...],
    budget: _CompositionProbeBudget,
    *,
    pair_only: bool,
) -> GuidanceStatus:
    """Run one private diagnostic solve; it never enters Arrangement history."""
    if budget.exhausted:
        raise RuntimeError("composition guidance probe budget is exhausted")
    result = resolve_design(
        source,
        DesignRequest(room=room, intents=intents, maxCandidates=MAX_CANDIDATES),
        zone_offer=zone_offer,
    )
    budget.probes_executed += 1
    budget.pair_probes += int(pair_only)
    budget.complete_design_probes += int(not pair_only)
    budget.candidate_checks += result.search.attemptedCandidates
    if result.status == "failed":
        status: GuidanceStatus = (
            "conclusively-invalid" if result.search.exhaustive else "unknown-bounded-search"
        )
    else:
        circulation = validate_circulation(result, CLEARANCE_WIDTH_M, anchor_ids=frozenset())
        if circulation.status == "clear":
            status = "witnessed-valid"
        else:
            status = (
                "conclusively-invalid" if circulation.exhaustive else "unknown-bounded-search"
            )
    if status == "unknown-bounded-search":
        budget.unknown_probes += 1
    return status


def _replacement_intents(
    intents: tuple[PlacementIntent, ...],
    replacements: tuple[PlacementIntent, ...],
) -> tuple[PlacementIntent, ...]:
    by_id = {intent.id: intent for intent in replacements}
    return tuple(by_id.get(intent.id, intent) for intent in intents)


def _pair_scope(
    intents: tuple[PlacementIntent, ...],
    replacements: tuple[PlacementIntent, ...],
) -> tuple[PlacementIntent, ...]:
    """Keep the affected dependency group plus only the context needed to solve it."""
    candidate = _replacement_intents(intents, replacements)
    by_id = {intent.id: intent for intent in candidate}
    affected = {intent.id for intent in replacements}
    changed = True
    while changed:
        changed = False
        for intent in candidate:
            if intent.referenceId in affected and intent.id not in affected:
                affected.add(intent.id)
                changed = True
        flanking_references = {
            by_id[request_id].referenceId
            for request_id in affected
            if by_id[request_id].kind == "flanking"
        }
        for intent in candidate:
            if (
                intent.kind == "flanking"
                and intent.referenceId in flanking_references
                and intent.id not in affected
            ):
                affected.add(intent.id)
                changed = True

    included = {ANCHOR_ID, *affected}
    for request_id in tuple(affected):
        reference_id = by_id[request_id].referenceId
        while reference_id is not None and reference_id not in included:
            included.add(reference_id)
            reference_id = by_id[reference_id].referenceId
    return tuple(intent for intent in candidate if intent.id in included)


def _gap_ladder(intent: PlacementIntent, intents: tuple[PlacementIntent, ...], eligible: tuple[Product, ...]) -> tuple[float, ...]:
    """Derive a short relation-gap ladder from the current request and authority scales."""
    if intent.gapM < 0:
        return ()
    products = {product.id: product for product in eligible}
    by_id = {item.id: item for item in intents}
    required_depth = 0.0
    if intent.referenceId is not None and intent.side is not None:
        reference = by_id[intent.referenceId]
        required_depth = max(
            (
                region.depthM
                for region in products[reference.productId].accessRegions
                if region.required and region.face == intent.side
            ),
            default=0.0,
        )
    baseline = max(intent.gapM, required_depth)
    return tuple(round(baseline + SEARCH_STEP_M * multiplier, 9) for multiplier in (1, 2, 4))


def _composition_alternatives(
    selection: ArrangementSelection,
    eligible: tuple[Product, ...],
    capabilities: WallCapabilityMap,
    zone_offer: ZoneOffer,
) -> tuple[_CompositionAlternative, ...]:
    """Enumerate bounded coordinate-free edits without changing identity or Product."""
    intents = selection.intents
    by_id = {intent.id: intent for intent in intents}
    alternatives: list[_CompositionAlternative] = []
    seen: set[bytes] = set()

    def add(replacements: tuple[PlacementIntent, ...]) -> None:
        request_ids = tuple(sorted(intent.id for intent in replacements))
        signature = json.dumps(
            [intent.model_dump(mode="json") for intent in replacements],
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if signature not in seen:
            seen.add(signature)
            alternatives.append(_CompositionAlternative(request_ids, replacements))

    handled_flanking: set[str] = set()
    for intent in sorted(intents, key=lambda item: (item.id == ANCHOR_ID, item.id)):
        if intent.kind in {"against", "centred_on", "in_corner"}:
            for option in capabilities[intent.productId]:
                if option.kind != intent.kind:
                    continue
                replacement = PlacementIntent.model_validate({
                    **intent.model_dump(mode="json"),
                    "wallId": option.wall_id,
                    "face": option.face,
                    "adjacentWallId": option.adjacent_wall_id,
                })
                if replacement != intent:
                    add((replacement,))
        elif intent.kind == "adjacent_to":
            for side in ("left", "right", "front", "back"):
                if side != intent.side:
                    add((PlacementIntent.model_validate({
                        **intent.model_dump(mode="json"), "side": side,
                    }),))
            for gap_m in _gap_ladder(intent, intents, eligible):
                add((PlacementIntent.model_validate({
                    **intent.model_dump(mode="json"), "gapM": gap_m,
                }),))
        elif intent.kind == "facing":
            for gap_m in _gap_ladder(intent, intents, eligible):
                add((PlacementIntent.model_validate({
                    **intent.model_dump(mode="json"), "gapM": gap_m,
                }),))
        elif intent.kind == "flanking" and intent.referenceId is not None:
            if intent.referenceId in handled_flanking:
                continue
            handled_flanking.add(intent.referenceId)
            group = tuple(
                item
                for item in intents
                if item.kind == "flanking" and item.referenceId == intent.referenceId
            )
            if len(group) == 2:
                for gap_m in _gap_ladder(intent, intents, eligible):
                    add(tuple(PlacementIntent.model_validate({
                        **item.model_dump(mode="json"), "gapM": gap_m,
                    }) for item in group))
        elif intent.kind == "in_zone":
            for zone in sorted(zone_offer.zones, key=lambda item: item.id):
                if zone.id != intent.zoneId:
                    add((PlacementIntent.model_validate({
                        **intent.model_dump(mode="json"), "zoneId": zone.id,
                    }),))

    # The original selection is already graph-valid. Constructed edits retain
    # all IDs/Products and only use admitted walls, offered Zones or grammar fields.
    assert all(
        replacement.id in by_id and replacement.productId == by_id[replacement.id].productId
        for alternative in alternatives
        for replacement in alternative.replacements
    )
    return tuple(alternatives)


def _guide_intents(intents: tuple[PlacementIntent, ...]) -> list[dict[str, Any]]:
    return [intent.model_dump(mode="json", exclude_none=True) for intent in intents]


def _bounded_composition_guide(value: dict[str, Any]) -> dict[str, Any]:
    """Prefer the complete witness, then trim pair-only examples to a hard byte cap."""
    bounded = value
    while len(json.dumps(bounded, separators=(",", ":"), sort_keys=True).encode("utf-8")) > MAX_COMPOSITION_GUIDANCE_BYTES:
        witnesses = bounded["pairWitnesses"]
        if witnesses:
            bounded = {**bounded, "pairWitnesses": witnesses[:-1], "optionsTruncated": True}
            continue
        if bounded["completeDesignWitness"] is not None:
            bounded = {
                **bounded,
                "completeDesignWitness": None,
                "completeWitnessOmittedForByteBound": True,
                "optionsTruncated": True,
            }
            continue
        raise ProviderCallError("configuration-error", "Composition correction guide exceeds its byte bound.")
    return bounded


def _composition_correction_guidance(
    source: Catalogue,
    room: RoomShell,
    zone_offer: ZoneOffer,
    eligible: tuple[Product, ...],
    capabilities: WallCapabilityMap,
    selection: ArrangementSelection,
    *,
    max_probes: int = MAX_COMPOSITION_GUIDANCE_PROBES,
) -> dict[str, Any]:
    """Derive advisory pair/full witnesses without mutating the live Arrangement."""
    if not 1 <= max_probes <= MAX_COMPOSITION_GUIDANCE_PROBES:
        raise ValueError("composition guidance probe bound must be between one and 32")
    budget = _CompositionProbeBudget(max_probes=max_probes)
    pair_witnesses: list[tuple[_CompositionAlternative, dict[str, Any]]] = []
    alternatives = _composition_alternatives(selection, eligible, capabilities, zone_offer)
    for alternative in alternatives:
        if budget.exhausted or budget.pair_probes >= min(MAX_COMPOSITION_PAIR_PROBES, max_probes):
            break
        pair_intents = _pair_scope(selection.intents, alternative.replacements)
        status = _probe_composition_intents(
            source, room, zone_offer, pair_intents, budget, pair_only=True,
        )
        if status == "witnessed-valid" and len(pair_witnesses) < MAX_COMPOSITION_PAIR_WITNESSES:
            pair_witnesses.append((alternative, {
                "status": "pair-only-witnessed-valid",
                "requestIds": list(alternative.request_ids),
                "validatedScopeRequestIds": [intent.id for intent in pair_intents],
                "replacementIntents": _guide_intents(alternative.replacements),
            }))

    complete_witness: dict[str, Any] | None = None
    seen_complete: set[bytes] = set()
    for size in range(1, len(pair_witnesses) + 1):
        if complete_witness is not None or budget.exhausted:
            break
        for chosen in combinations(pair_witnesses, size):
            if budget.exhausted:
                break
            request_ids = [request_id for alternative, _ in chosen for request_id in alternative.request_ids]
            if len(set(request_ids)) != len(request_ids):
                continue
            replacements = tuple(
                intent
                for alternative, _ in chosen
                for intent in alternative.replacements
            )
            candidate = _replacement_intents(selection.intents, replacements)
            signature = json.dumps(
                [intent.model_dump(mode="json") for intent in candidate],
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if signature in seen_complete:
                continue
            seen_complete.add(signature)
            status = _probe_composition_intents(
                source, room, zone_offer, candidate, budget, pair_only=False,
            )
            if status == "witnessed-valid":
                complete_witness = {
                    "status": "complete-design-witnessed-valid",
                    "changedRequestIds": sorted(request_ids),
                    "replacementIntents": _guide_intents(replacements),
                    "preservedRequestIds": [intent.id for intent in selection.intents],
                }
                break

    guide = {
        "method": "bounded-authoritative-composition-v1",
        "scope": (
            "Server-authored coordinate-free diagnostic options for the previous failed selection. "
            "Pair witnesses are not complete Designs; the provider must return the full identity set and the server re-solves it."
        ),
        "maxProbes": max_probes,
        "maxPairProbes": min(MAX_COMPOSITION_PAIR_PROBES, max_probes),
        "probesExecuted": budget.probes_executed,
        "pairProbes": budget.pair_probes,
        "completeDesignProbes": budget.complete_design_probes,
        "candidateChecks": budget.candidate_checks,
        "unknownProbes": budget.unknown_probes,
        "budgetExhausted": budget.exhausted,
        "optionsTruncated": (
            len(pair_witnesses) >= MAX_COMPOSITION_PAIR_WITNESSES
            or budget.pair_probes < len(alternatives)
        ),
        "pairWitnesses": [value for _, value in pair_witnesses],
        "completeDesignWitness": complete_witness,
    }
    return _bounded_composition_guide(guide)


_REJECTED_DRAFT_FIELDS = {
    "id", "kind", "productId", "wallId", "face", "adjacentWallId",
    "zoneId", "referenceId", "side", "gapM",
}
MAX_REJECTED_DRAFT_BYTES = 8_192
_SAFE_REJECTION_PATH_FIELDS = _REJECTED_DRAFT_FIELDS | {"intents"}
_CANONICAL_INTENT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _safe_rejection_path(location: tuple[Any, ...]) -> str | None:
    parts: list[str] = []
    for part in location:
        if isinstance(part, int) and 0 <= part < 20:
            parts.append(str(part))
        elif isinstance(part, str) and part in _SAFE_REJECTION_PATH_FIELDS:
            parts.append(part)
    return ".".join(parts)[:160] or None


def _safe_intent_id(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 64 or _CANONICAL_INTENT_ID.fullmatch(value) is None:
        return None
    return value


def _bounded_rejected_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Retain only bounded grammar fields; never echo arbitrary provider content."""
    raw_intents = payload.get("intents")
    if not isinstance(raw_intents, list):
        return {"shape": "intents-not-an-array"}
    intents: list[dict[str, Any]] = []
    for raw in raw_intents[:20]:
        if not isinstance(raw, dict):
            intents.append({"shape": "intent-not-an-object"})
            continue
        cleaned: dict[str, Any] = {}
        for key in sorted(_REJECTED_DRAFT_FIELDS & raw.keys()):
            value = raw[key]
            if isinstance(value, str):
                cleaned[key] = value[:100]
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cleaned[key] = max(-1000, min(1000, value))
            elif value is None:
                cleaned[key] = None
            else:
                cleaned[key] = "invalid-type"
        candidate = {"intents": [*intents, cleaned], "truncated": True}
        if len(json.dumps(candidate, separators=(",", ":"), sort_keys=True).encode("utf-8")) > MAX_REJECTED_DRAFT_BYTES:
            break
        intents.append(cleaned)
    return {"intents": intents, "truncated": len(intents) < len(raw_intents)}


def _prompt(
    *,
    eligible: tuple[Product, ...],
    room: RoomShell,
    zone_offer: ZoneOffer,
    capabilities: WallCapabilityMap,
    bed_guidance: dict[str, Any],
    provider_call_index: int,
    previous: ArrangementSelection | None,
    session: ArrangementSession | None,
    composition_guidance: dict[str, Any] | None = None,
    correction: SelectionRejection | None = None,
    rejected_draft: dict[str, Any] | None = None,
) -> str:
    product_view = [{
        "id": product.id,
        "category": product.category,
        "dimensionsM": product.dimensionsM.model_dump(mode="json"),
        "placementClass": product.placementClass,
        "wallContactFaces": product.wallContactFaces,
        "allowedIntentKinds": [
            *sorted({item.kind for item in capabilities[product.id]}),
            "adjacent_to", "facing", "flanking", "in_zone",
        ],
        "wallPlacementOptions": _capability_prompt_rows(capabilities[product.id]),
        "requiredAccess": [region.model_dump(mode="json") for region in product.accessRegions if region.required],
    } for product in eligible]
    immutable = None
    feedback = None
    history = None
    complete_design_status = None
    prompt_bed_guidance = bed_guidance
    if previous is not None and session is not None:
        initial = session.selections[0]
        initial_bed = next(intent for intent in initial.intents if intent.id == ANCHOR_ID)
        prompt_bed_guidance = {
            **bed_guidance,
            "bedWallOptionsByProduct": {
                initial_bed.productId: bed_guidance["bedWallOptionsByProduct"][initial_bed.productId],
            },
        }
        immutable = {
            "identitySet": [intent.id for intent in initial.intents],
            "requiredBed": {"id": ANCHOR_ID, "productId": initial_bed.productId},
            "bedSpatialIntentMayChange": True,
            "categories": {
                intent.id: next(product.category for product in eligible if product.id == intent.productId)
                for intent in initial.intents
            },
        }
        feedback = session.latest_attempt.model_dump(mode="json") if session.latest_attempt else None
        history = [attempt.model_dump(mode="json") for attempt in session.attempts]
        if session.latest_attempt is not None:
            constraint = session.latest_attempt.limitingConstraint
            complete_design_status = (
                "conclusively-invalid"
                if constraint is not None and constraint.exhaustive is True
                else "unknown-bounded-search"
            )
    placement_guidance = {
        **prompt_bed_guidance,
        "completeDesignStatus": complete_design_status,
        "accessRelationshipRule": (
            "Do not place adjacent_to or flanking furniture inside a referenced Product's required access face: "
            "gapM must be at least that face's required depth. This is necessary, not sufficient; the server re-solves the complete Design."
        ),
        "accessRelationshipWarnings": _access_relationship_warnings(previous, eligible),
        "compositionCorrection": composition_guidance,
    }
    context = {
        "task": (
            "Select a technically valid bedroom Design inspired by the attached reference pixels. "
            "Return exactly one eligible bed and zero or one eligible rug. "
            "Return only Product ids and coordinate-free Placement Intents. Never emit coordinates, Room geometry, policy, credentials, or provider settings."
        ),
        "roomType": "bedroom",
        "room": room.model_dump(mode="json"),
        "offeredZones": [zone.model_dump(mode="json") for zone in zone_offer.zones],
        "eligibleCatalogue": product_view,
        "rules": {
            "anchor": f"Exactly one bed is required and its request id must be {ANCHOR_ID}.",
            "selectionScope": {
                "version": LIVE_SELECTION_SCOPE_VERSION,
                "required": {"category": "bed", "count": 1, "requestId": ANCHOR_ID},
                "optional": {"category": "rug", "minimumCount": 0, "maximumCount": 1},
                "maximumRequests": 2,
                "otherCategories": "forbidden",
                "instruction": (
                    "Do not return nightstands, dressers, wardrobes, chairs, lamps, another bed, or more than one rug. "
                    "Repairs must not add or remove a request."
                ),
            },
            "requestLimit": 2,
            "operations": ["against", "centred_on", "in_corner", "adjacent_to", "facing", "flanking", "in_zone"],
            "relativeGrammar": {
                "adjacentTo": (
                    "Use one adjacent_to request for one related Product."
                ),
                "flanking": {
                    "invariant": (
                        "A flanking group has exactly two distinct requests with the same referenceId and gapM: "
                        "one side left and one side right. Never emit a singleton flanking request."
                    ),
                    "scope": "Grammar only; the current two-request selection limit cannot form a flanking group with the required bed.",
                },
            },
            "wallOptionTuple": ["kind", "wallId", "face", "adjacentWallId", "secondaryFace"],
            "wallCapability": (
                "Every wall operation must exactly match one Product wallPlacementOptions tuple. "
                "An empty list forbids wall operations. secondaryFace is informative and is not an output field."
            ),
            "repair": (
                "Repairs must preserve every request id, the required bed Product id, and each request's Product category. "
                "The bed's coordinate-free spatial Placement Intent may change; the server re-solves all physical constraints."
            ),
            "feasibility": (
                "Prefer witnessed-valid bed-only options, never treat unknown-bounded-search as impossible, and avoid conclusively-invalid options. "
                "Bed-only status does not validate other furniture or whole-Design circulation; respond to complete-Design feedback and access warnings."
            ),
        },
        "placementGuidance": placement_guidance,
        "providerCallNumber": provider_call_index + 1,
        "validSelectionNumber": len(session.selections) if session else 0,
        "repairNumber": len(session.selections) if session else 0,
        "previousSelection": previous.model_dump(mode="json") if previous else None,
        "immutableRepairContract": immutable,
        "actualPrecedingFeedback": feedback,
        "chronologicalHistory": history,
        "correctionFeedback": correction.model_dump(mode="json") if correction else None,
        "rejectedDraft": rejected_draft,
    }
    prompt = json.dumps(context, separators=(",", ":"), sort_keys=True)
    if len(prompt.encode("utf-8")) > MAX_PROMPT_TEXT_BYTES:
        raise ProviderCallError(
            "configuration-error",
            f"Provider prompt exceeds the {MAX_PROMPT_TEXT_BYTES}-byte bound.",
        )
    return prompt


def _category_policy(category: ProductCategory) -> Literal["decoration", "secondary-furniture"]:
    if category in {"rug", "lamp"}:
        return "decoration"
    if category in {"nightstand", "wardrobe", "dresser", "chair"}:
        return "secondary-furniture"
    raise ValueError(f'Product category "{category}" is not eligible for the bedroom optional policy.')


def _validate_graph(
    intents: tuple[PlacementIntent, ...],
    products: dict[str, Product],
    zone_offer: ZoneOffer,
    capabilities: WallCapabilityMap,
) -> None:
    def reject(
        code: SelectionRejectionCode,
        detail: str,
        *,
        path: str | None = None,
        intent_id: str | None = None,
    ) -> None:
        raise SelectionRejected(SelectionRejection(
            code=code,
            detail=detail,
            path=path,
            intentId=intent_id,
        ))

    ids = [intent.id for intent in intents]
    if len(set(ids)) != len(ids):
        reject("graph-error", "Placement Intent request ids must be unique.", path="intents.id")
    known = set(ids)
    zones = {zone.id for zone in zone_offer.zones}
    for index, intent in enumerate(intents):
        product = products[intent.productId]
        if intent.kind in {"against", "centred_on", "in_corner"}:
            admitted = any(
                option.kind == intent.kind
                and option.wall_id == intent.wallId
                and option.face == intent.face
                and option.adjacent_wall_id == intent.adjacentWallId
                for option in capabilities[product.id]
            )
            if not admitted:
                if intent.kind == "in_corner":
                    reject(
                        "corner-face-error",
                        f'Intent "{intent.id}" does not match a permitted corner tuple for Product "{product.id}".',
                        path=f"intents.{index}.adjacentWallId",
                        intent_id=intent.id,
                    )
                reject(
                    "wall-face-error",
                    f'Intent "{intent.id}" does not match a permitted wall tuple for Product "{product.id}".',
                    path=f"intents.{index}.face",
                    intent_id=intent.id,
                )
        if intent.zoneId is not None and intent.zoneId not in zones:
            reject(
                "graph-error",
                f'Intent "{intent.id}" references an unknown offered Zone.',
                path=f"intents.{index}.zoneId",
                intent_id=intent.id,
            )
        if intent.referenceId is not None:
            if intent.referenceId not in known:
                reject(
                    "graph-error", f'Intent "{intent.id}" references a missing request.',
                    path=f"intents.{index}.referenceId", intent_id=intent.id,
                )
            if intent.referenceId == intent.id:
                reject(
                    "graph-error", f'Intent "{intent.id}" references itself.',
                    path=f"intents.{index}.referenceId", intent_id=intent.id,
                )
        if intent.gapM < 0:
            if intent.kind != "adjacent_to" or intent.referenceId is None:
                reject(
                    "graph-error", "Negative gap is supported only for adjacent floor-covering overlap.",
                    path=f"intents.{index}.gapM", intent_id=intent.id,
                )
            classes = {product.placementClass, products[next(item.productId for item in intents if item.id == intent.referenceId)].placementClass}
            if classes != {"floor-covering", "floor-standing"}:
                reject(
                    "graph-error", "Negative gap requires a floor-covering and floor-standing pair.",
                    path=f"intents.{index}.gapM", intent_id=intent.id,
                )
            reference_product = products[next(item.productId for item in intents if item.id == intent.referenceId)]
            axis = "widthM" if intent.side in {"left", "right"} else "depthM"
            separation = getattr(product.dimensionsM, axis) / 2 + getattr(reference_product.dimensionsM, axis) / 2 + intent.gapM
            if separation < -1e-9:
                reject(
                    "graph-error", "Negative gap reverses the requested side instead of creating overlap.",
                    path=f"intents.{index}.gapM", intent_id=intent.id,
                )
    flanking: dict[str, list[PlacementIntent]] = {}
    for intent in intents:
        if intent.kind == "flanking" and intent.referenceId:
            flanking.setdefault(intent.referenceId, []).append(intent)
    for members in flanking.values():
        if len(members) != 2 or {item.side for item in members} != {"left", "right"} or len({item.gapM for item in members}) != 1:
            reject("graph-error", "A flanking group requires one left and one right request with one gap.")
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {intent.id: intent for intent in intents}

    def visit(request_id: str) -> None:
        if request_id in visiting:
            reject("graph-error", "Placement Intent references contain a cycle.", intent_id=request_id)
        if request_id in visited:
            return
        visiting.add(request_id)
        reference_id = by_id[request_id].referenceId
        if reference_id:
            visit(reference_id)
        visiting.remove(request_id)
        visited.add(request_id)

    for request_id in sorted(known):
        visit(request_id)


def _validated_selection(
    payload: dict[str, Any],
    eligible: tuple[Product, ...],
    *,
    room: RoomShell,
    zone_offer: ZoneOffer,
    capabilities: WallCapabilityMap,
    selection_id: str,
    initial: ArrangementSelection | None,
    enforce_live_scope: bool = False,
) -> ArrangementSelection:
    try:
        selection = ProviderSelection.model_validate(payload)
    except ValidationError as error:
        item = error.errors(include_input=False, include_url=False)[0]
        location = tuple(item["loc"])
        path = _safe_rejection_path(location)
        intent_index = next((part for part in location if isinstance(part, int)), None)
        intent_id = None
        raw_intents = payload.get("intents")
        if isinstance(intent_index, int) and isinstance(raw_intents, list) and intent_index < len(raw_intents):
            raw_intent = raw_intents[intent_index]
            if isinstance(raw_intent, dict):
                intent_id = _safe_intent_id(raw_intent.get("id"))
        raise SelectionRejected(SelectionRejection(
            code="operation-shape-error",
            detail="Selection does not match the strict fields for one supported Placement operation.",
            path=path,
            intentId=intent_id,
        )) from None
    products = {product.id: product for product in eligible}
    unknown = sorted({intent.productId for intent in selection.intents} - set(products))
    if unknown:
        raise SelectionRejected(SelectionRejection(
            code="ineligible-product-error",
            detail=f'Selection uses ineligible Product id "{unknown[0][:100]}".',
            path="intents.productId",
        ))
    intents = tuple(PlacementIntent.model_validate(intent.model_dump(mode="json")) for intent in selection.intents)
    beds = [intent for intent in intents if products[intent.productId].category == "bed"]
    if len(beds) != 1 or beds[0].id != ANCHOR_ID:
        raise SelectionRejected(SelectionRejection(
            code="anchor-error",
            detail=f'Exactly one bed with request id "{ANCHOR_ID}" is required.',
            path="intents.id",
            intentId=beds[0].id if len(beds) == 1 else None,
        ))
    _validate_graph(intents, products, zone_offer, capabilities)
    candidate = ArrangementSelection(id=selection_id, intents=intents)
    if initial is not None:
        initial_by_id = {intent.id: intent for intent in initial.intents}
        current_by_id = {intent.id: intent for intent in candidate.intents}
        if set(current_by_id) != set(initial_by_id):
            raise SelectionRejected(SelectionRejection(
                code="repair-identity-error",
                detail="Repair must preserve the initial request identity set.",
                path="intents.id",
            ))
        if current_by_id[ANCHOR_ID].productId != initial_by_id[ANCHOR_ID].productId:
            raise SelectionRejected(SelectionRejection(
                code="repair-anchor-error",
                detail="Repair must preserve the required bed Product identity.",
                path="intents.productId",
                intentId=ANCHOR_ID,
            ))
        for request_id, first in initial_by_id.items():
            if products[current_by_id[request_id].productId].category != products[first.productId].category:
                raise SelectionRejected(SelectionRejection(
                    code="repair-category-error",
                    detail=f'Repair changed the Product category of request "{request_id[:64]}".',
                    path="intents.productId",
                    intentId=request_id,
                ))
    categories = [products[intent.productId].category for intent in intents]
    if enforce_live_scope and (
        any(category not in LIVE_SELECTION_CATEGORIES for category in categories)
        or len(intents) > 2
        or categories.count("rug") > 1
    ):
        raise SelectionRejected(SelectionRejection(
            code="selection-scope-error",
            detail="The current live stage accepts exactly one bed and zero or one rug.",
            path="intents",
        ))
    return candidate


def _generation_error_code(code: str) -> GenerationFailureCode:
    return "provider-schema-error" if code == "schema-error" else code  # type: ignore[return-value]


def _policies(selection: ArrangementSelection, eligible: tuple[Product, ...]) -> tuple[PlacementPolicy, ...]:
    products = {product.id: product for product in eligible}
    return tuple(PlacementPolicy(
        requestId=intent.id,
        required=intent.id == ANCHOR_ID,
        anchor=intent.id == ANCHOR_ID,
        optionalKind=None if intent.id == ANCHOR_ID else _category_policy(products[intent.productId].category),
    ) for intent in selection.intents)


def _live_selection_products(products: tuple[Product, ...]) -> tuple[Product, ...]:
    """Narrow Style eligibility only at the live provider boundary."""
    return tuple(product for product in products if product.category in LIVE_SELECTION_CATEGORIES)


def generate_live_bedroom(
    source: Catalogue,
    request: LiveGenerationRequest,
    *,
    provider: GenerationProvider | None = None,
    generation_id_factory: Callable[[], str] = lambda: str(uuid4()),
) -> LiveGenerationResultValue:
    generation_id = generation_id_factory()
    manifest = reference_manifest()
    reference = next((item for item in manifest.images if item.id == request.referenceId), None)
    if reference is None:
        return _failure(generation_id, request.referenceId, "configuration-error", "The selected reference is unavailable.", 0, 0, [])
    style_eligible = source.list(CatalogueQuery(room_type=request.roomType, private_style_id=reference.privateStyleId))
    eligible = _live_selection_products(style_eligible)
    eligible_beds = tuple(product for product in eligible if product.category == "bed")
    if not eligible_beds:
        return _failure(
            generation_id,
            request.referenceId,
            "eligible-catalogue-error",
            "No bed is eligible for the selected image; generation was not sent to the provider.",
            0,
            0,
            [],
        )
    try:
        image = verified_reference(reference)
        active_provider = provider or AnthropicProvider(ProviderSettings.from_environment())
    except ProviderCallError as error:
        return _failure(generation_id, request.referenceId, error.code, error.detail, 0, 0, [])

    room = intent_fixture_room()
    zone_offer = derive_zones(room)
    capabilities = _wall_capability_map(room, style_eligible)
    deadline_at = monotonic() + OVERALL_DEADLINE_SECONDS
    bed_guidance = _bed_placement_guidance(source, room, zone_offer, eligible, capabilities)
    calls = 0
    latency_ms = 0
    usages: list[ProviderUsage | None] = []
    session: ArrangementSession | None = None
    previous: ArrangementSelection | None = None
    rejections: list[SelectionRejection] = []
    correction: SelectionRejection | None = None
    rejected_draft: dict[str, Any] | None = None
    composition_guidance: dict[str, Any] | None = None

    for call_index in range(MAX_REPAIR_ATTEMPTS + 1):
        try:
            prompt = _prompt(
                eligible=eligible,
                room=room,
                zone_offer=zone_offer,
                capabilities=capabilities,
                bed_guidance=bed_guidance,
                provider_call_index=call_index,
                previous=previous,
                session=session,
                composition_guidance=composition_guidance,
                correction=correction,
                rejected_draft=rejected_draft,
            )
        except ProviderCallError as error:
            history = session.failure_snapshot(
                "Generation stopped because bounded correction context could not be prepared; no optional drops were attempted."
            ) if session is not None and session.latest_attempt is not None else None
            return _failure(
                generation_id, request.referenceId, error.code, error.detail, calls, latency_ms, usages,
                history, tuple(rejections),
            )
        calls += 1  # The bounded attempt is consumed before provider I/O.
        attempt_started = monotonic()
        try:
            reply = active_provider.generate(
                prompt_text=prompt,
                image_media_type="image/jpeg",
                image_base64=base64.b64encode(image).decode("ascii"),
                output_schema=_output_schema(),
                deadline_at=deadline_at,
            )
        except ProviderCallError as error:
            latency_ms += round((monotonic() - attempt_started) * 1000)
            if error.attempted:
                usages.append(error.usage if isinstance(error.usage, ProviderUsage) else None)
            history = session.failure_snapshot(
                "Generation stopped after a provider failure; no optional drops were attempted."
            ) if session is not None and session.latest_attempt is not None else None
            return _failure(
                generation_id,
                request.referenceId,
                _generation_error_code(error.code),
                error.detail,
                calls,
                latency_ms,
                usages,
                history,
                tuple(rejections),
            )
        latency_ms += round((monotonic() - attempt_started) * 1000)
        usages.append(reply.usage)
        if monotonic() > deadline_at:
            history = session.failure_snapshot(
                "Generation stopped after the overall deadline; no optional drops were attempted."
            ) if session is not None and session.latest_attempt is not None else None
            return _failure(
                generation_id, request.referenceId, "timeout", "The overall generation deadline elapsed.",
                calls, latency_ms, usages, history, tuple(rejections),
            )
        if reply.model != MODEL_ID or reply.stop_reason != "end_turn":
            history = session.failure_snapshot(
                "Generation stopped after a provider protocol failure; no optional drops were attempted."
            ) if session is not None and session.latest_attempt is not None else None
            return _failure(
                generation_id,
                request.referenceId,
                "provider-schema-error",
                "Provider response did not match the exact requested model and successful stop reason.",
                calls,
                latency_ms,
                usages,
                history,
                tuple(rejections),
            )
        try:
            selection = _validated_selection(
                reply.payload,
                style_eligible,
                room=room,
                zone_offer=zone_offer,
                capabilities=capabilities,
                selection_id="initial" if session is None else f"repair-{len(session.selections)}",
                initial=session.selections[0] if session else None,
                enforce_live_scope=True,
            )
        except SelectionRejected as error:
            correction = error.rejection
            rejected_draft = _bounded_rejected_draft(reply.payload)
            rejections.append(error.rejection)
            continue

        if session is None:
            policies = _policies(selection, eligible)
            arrangement_request = ArrangementRequest(
                room=room,
                selections=(selection,),
                policies=policies,
                clearanceWidthM=CLEARANCE_WIDTH_M,
                maxCandidates=MAX_CANDIDATES,
            )
            session = ArrangementSession(
                source,
                arrangement_request,
                selection_limit=3,
                zone_offer=zone_offer,
                repositionable_request_ids=frozenset({ANCHOR_ID}),
            )
        solved = session.submit(selection)
        if solved is not None:
            return LiveGenerationSuccess(
                status="solved",
                generationId=generation_id,
                referenceId=request.referenceId,
                providerModel=reply.model,
                providerCalls=calls,
                modelLatencyMs=latency_ms,
                usage=_usage_summary(usages),
                selectionRejections=tuple(rejections),
                design=solved,
            )
        previous = selection
        correction = None
        rejected_draft = None
        if call_index < MAX_REPAIR_ATTEMPTS:
            composition_guidance = _composition_correction_guidance(
                source,
                room,
                zone_offer,
                eligible,
                capabilities,
                selection,
                max_probes=MAX_COMPOSITION_GUIDANCE_PROBES,
            )

    if session is None or len(session.selections) < MAX_REPAIR_ATTEMPTS + 1:
        history = session.failure_snapshot(
            "The three-call correction ceiling was reached before three valid solve attempts; no optional drops were attempted."
        ) if session is not None and session.latest_attempt is not None else None
        return _failure(
            generation_id,
            request.referenceId,
            "selection-correction-exhausted",
            "The provider selection correction ceiling was reached before the optional-drop prerequisite.",
            calls,
            latency_ms,
            usages,
            history,
            tuple(rejections),
        )

    final = session.finish()
    if final.status == "solved":
        return LiveGenerationSuccess(
            status="solved",
            generationId=generation_id,
            referenceId=request.referenceId,
            providerModel=MODEL_ID,
            providerCalls=calls,
            modelLatencyMs=latency_ms,
            usage=_usage_summary(usages),
            selectionRejections=tuple(rejections),
            design=final,
        )
    return _failure(
        generation_id,
        request.referenceId,
        "no-valid-design",
        final.detail,
        calls,
        latency_ms,
        usages,
        final,
        tuple(rejections),
    )


def frozen_generation_configuration(source: Catalogue) -> dict[str, Any]:
    """Versioned provider/solver policy inputs used by external gate tooling."""
    manifest = reference_manifest()
    room = intent_fixture_room()
    zone_offer = derive_zones(room)
    products = tuple(sorted(source.list(), key=lambda product: product.id))
    capabilities_by_product = _wall_capability_map(room, products)
    style_eligible_by_reference = {
        reference.id: sorted(product.id for product in source.list(CatalogueQuery(
            room_type="bedroom",
            private_style_id=reference.privateStyleId,
        )))
        for reference in manifest.images
    }
    eligible_by_reference = {
        reference.id: sorted(
            product.id
            for product in _live_selection_products(source.list(CatalogueQuery(
                room_type="bedroom",
                private_style_id=reference.privateStyleId,
            )))
        )
        for reference in manifest.images
    }
    prompts_by_reference: dict[str, str] = {}
    for reference in manifest.images:
        eligible = _live_selection_products(source.list(CatalogueQuery(
            room_type="bedroom",
            private_style_id=reference.privateStyleId,
        )))
        capabilities = _wall_capability_map(room, eligible)
        prompts_by_reference[reference.id] = _prompt(
            eligible=eligible,
            room=room,
            zone_offer=zone_offer,
            capabilities=capabilities,
            bed_guidance=_bed_placement_guidance(source, room, zone_offer, eligible, capabilities),
            provider_call_index=0,
            previous=None,
            session=None,
        )
    return {
        "version": "ticket-6-generation-config-v9",
        "room": room.model_dump(mode="json"),
        "zones": [zone.model_dump(mode="json") for zone in zone_offer.zones],
        "catalogueVersion": source.version,
        "catalogue": {
            "products": [product.model_dump(mode="json") for product in products],
            "privateStyleIdsByProduct": {
                product.id: list(source.private_style_ids(product.id))
                for product in products
            },
            "eligibleProductIdsByReference": eligible_by_reference,
            "styleEligibleProductIdsByReference": style_eligible_by_reference,
            "wallPlacementCapabilitiesByProduct": {
                product.id: _capability_prompt_rows(capabilities_by_product[product.id])
                for product in products
            },
        },
        "references": [record.model_dump(mode="json") for record in manifest.images],
        "proposedTenRunSchedule": list(manifest.proposedTenRunSchedule),
        "provider": {
            "model": MODEL_ID,
            "thinking": {"type": "adaptive"},
            "effort": "high",
            "format": "json_schema",
            "maxOutputTokens": 8192,
            "conservativeInputTokenReservation": CONSERVATIVE_INPUT_TOKEN_RESERVATION,
            "maxPromptBytes": MAX_PROMPT_TEXT_BYTES,
            "maxProviderSchemaBytes": MAX_PROVIDER_SCHEMA_BYTES,
            "maxImageBytes": MAX_IMAGE_BYTES,
            "maxImageEdgePx": MAX_IMAGE_EDGE_PX,
            "maxImageShortEdgePx": MAX_IMAGE_SHORT_EDGE_PX,
            "maxImageVisualTokens": MAX_IMAGE_VISUAL_TOKENS,
            "maxSerializedRequestBytes": MAX_SERIALIZED_REQUEST_BYTES,
            "maxResponseBytes": MAX_RESPONSE_BYTES,
            "automaticRetries": 0,
            "selectionGrammar": "strict-anyOf-v6-bed-plus-optional-rug",
            "selectionScope": {
                "version": LIVE_SELECTION_SCOPE_VERSION,
                "requiredBedCount": 1,
                "optionalRugMinimumCount": 0,
                "optionalRugMaximumCount": 1,
                "maximumRequests": 2,
                "allowedCategories": sorted(LIVE_SELECTION_CATEGORIES),
                "enforcedOn": ["initial", "repair"],
                "silentFiltering": False,
            },
            "selectionCorrectionCalls": 3,
            "optionalDropRequiresValidSolves": 3,
            "compositionGuidance": {
                "diagnosticScope": "changed-anchor-or-request-transitive-dependents-atomic-flanking-and-ancestors-v3",
                "repairBedGuidance": "selected-anchor-product-only",
                "maxAuthorityProbesPerFailedSelection": MAX_COMPOSITION_GUIDANCE_PROBES,
                "maxPairProbes": MAX_COMPOSITION_PAIR_PROBES,
                "maxPairWitnesses": MAX_COMPOSITION_PAIR_WITNESSES,
                "maxBytes": MAX_COMPOSITION_GUIDANCE_BYTES,
                "gapStepM": SEARCH_STEP_M,
                "gapStepMultipliers": [1, 2, 4],
            },
            "localAccountingModes": ["capped", "uncapped"],
            "uncappedModeExplicitOptIn": True,
            "credentialFileConflictingDirectOverrides": "rejected",
        },
        "solver": {
            "clearanceWidthM": CLEARANCE_WIDTH_M,
            "maxCandidatesPerSolve": MAX_CANDIDATES,
            "maxRequests": 20,
            "maxRepairs": MAX_REPAIR_ATTEMPTS,
            "maxSolves": MAX_ARRANGEMENT_SOLVES,
            "anchorId": ANCHOR_ID,
            "optionalPolicy": {
                "decoration": ["rug", "lamp"],
                "secondary-furniture": ["nightstand", "wardrobe", "dresser", "chair"],
            },
        },
        "promptContractSha256": hashlib.sha256(
            prompts_by_reference[manifest.images[0].id].encode("utf-8")
        ).hexdigest(),
        "promptContractSha256ByReference": {
            reference.id: hashlib.sha256(prompts_by_reference[reference.id].encode("utf-8")).hexdigest()
            for reference in manifest.images
        },
        "promptContractBytesByReference": {
            reference.id: len(prompts_by_reference[reference.id].encode("utf-8"))
            for reference in manifest.images
        },
        "providerOutputSchemaSha256": hashlib.sha256(
            json.dumps(_output_schema(), separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "providerOutputSchemaBytes": len(
            json.dumps(_output_schema(), separators=(",", ":"), sort_keys=True).encode("utf-8")
        ),
    }
