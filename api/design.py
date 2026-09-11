"""Deterministic accepted bedroom Design."""
from __future__ import annotations

from .catalogue import Catalogue, catalogue
from .domain import place_against_wall, resolve_design
from .models import (
    DesignFailure, DesignFixture, DesignFixtures, DesignRequest, DesignResultValue,
    FixtureSelectionRequest, PreviewDesign, RoomShell, SearchReport,
)

FEATURED_PRODUCT_ID = "bed-prudence-tufted-queen-natural"


def bedroom_room_shell() -> RoomShell:
    return RoomShell.model_validate({
        "id": "room-bedroom-4x3",
        "floorPolygon": [[-2, -1.5], [-2, 1.5], [2, 1.5], [2, -1.5]],
        "ceilingHeightM": 2.5,
        "walls": [
            {"id": "wall-north", "label": "North wall", "start": [-2, -1.5], "end": [2, -1.5]},
            {"id": "wall-east", "label": "East wall", "start": [2, -1.5], "end": [2, 1.5]},
            {"id": "wall-south", "label": "South wall", "start": [2, 1.5], "end": [-2, 1.5]},
            {"id": "wall-west", "label": "West wall", "start": [-2, 1.5], "end": [-2, -1.5]},
        ],
    })


def bedroom_design(source: Catalogue = catalogue) -> PreviewDesign:
    product = source.get(FEATURED_PRODUCT_ID)
    if product is None:
        raise RuntimeError(f"Catalogue has no Product {FEATURED_PRODUCT_ID}")
    room = bedroom_room_shell()
    return PreviewDesign(room=room, product=product, fit=place_against_wall(product, room, "wall-north", "back"))


def intent_fixture_room() -> RoomShell:
    """The established 4 x 3 m bedroom with a raised window and inward-swinging door."""
    return RoomShell.model_validate({
        "id": "room-bedroom-wall-intent",
        "floorPolygon": [[-2, -1.5], [-2, 1.5], [2, 1.5], [2, -1.5]],
        "ceilingHeightM": 2.5,
        "walls": [
            {"id": "wall-north", "label": "North wall", "start": [-2, -1.5], "end": [2, -1.5]},
            {"id": "wall-east", "label": "East wall", "start": [2, -1.5], "end": [2, 1.5]},
            {"id": "wall-south", "label": "South wall", "start": [2, 1.5], "end": [-2, 1.5]},
            {"id": "wall-west", "label": "West wall", "start": [-2, 1.5], "end": [-2, -1.5]},
        ],
        "openings": [
            {
                "id": "south-window",
                "kind": "window",
                "wallId": "wall-south",
                "offsetAlongWallM": 0,
                "widthM": 1.2,
                "bottomM": 1.2,
                "heightM": 1.0,
                "clearanceDepthM": 0.3,
            },
            {
                "id": "bedroom-door",
                "kind": "door",
                "wallId": "wall-east",
                "offsetAlongWallM": -1.0,
                "widthM": 1.0,
                "bottomM": 0,
                "heightM": 2.1,
                "clearanceDepthM": 0,
                "doorSwing": {"hingeSide": "start"},
            },
        ],
    })


def object_intent_fixture_room() -> RoomShell:
    """A roomy bedroom for visible related-Product, rug and floor-lamp fixtures."""
    return RoomShell.model_validate({
        "id": "room-bedroom-object-intent",
        "floorPolygon": [[-3.5, -3], [-3.5, 3], [3.5, 3], [3.5, -3]],
        "ceilingHeightM": 2.5,
        "walls": [
            {"id": "wall-north", "label": "North wall", "start": [-3.5, -3], "end": [3.5, -3]},
            {"id": "wall-east", "label": "East wall", "start": [3.5, -3], "end": [3.5, 3]},
            {"id": "wall-south", "label": "South wall", "start": [3.5, 3], "end": [-3.5, 3]},
            {"id": "wall-west", "label": "West wall", "start": [-3.5, 3], "end": [-3.5, -3]},
        ],
        "openings": [
            {
                "id": "object-room-door",
                "kind": "door",
                "wallId": "wall-east",
                "offsetAlongWallM": -2,
                "widthM": 1,
                "bottomM": 0,
                "heightM": 2.1,
                "clearanceDepthM": 0,
                "doorSwing": {"hingeSide": "start"},
            },
        ],
    })


_FIXTURES = (
    DesignFixture(
        id="against-wall",
        label="Bed against the north wall",
        description="Places the bed flush with the north wall, facing into the Room.",
        intentKind="against",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="centred-on-wall",
        label="Dresser centred on the south wall",
        description="Aligns the dresser with the middle of the south wall, below the window.",
        intentKind="centred_on",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="in-corner",
        label="Nightstand in the north-west corner",
        description="Tucks the nightstand into the corner shared by the north and west walls.",
        intentKind="in_corner",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="door-swing-failure",
        label="Nightstand in the door swing",
        description="Shows why the north-east corner must stay clear for the bedroom door.",
        intentKind="in_corner",
        expectedOutcome="failed",
    ),
    DesignFixture(
        id="matching-nightstands",
        label="Matching nightstands on opposite walls",
        description="Places two matching nightstands at the centres of the north and south walls.",
        intentKind="centred_on",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="adjacent-nightstand",
        label="Nightstand adjacent to the bed",
        description="Leaves 60 cm between the bed and a nightstand on its right.",
        intentKind="adjacent_to",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="facing-chair",
        label="Chair facing the bed",
        description="Places the chair in front of the bed and turns it toward the bed.",
        intentKind="facing",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="flanking-nightstands",
        label="Matching nightstands flank the bed",
        description="Places one matching nightstand on each side of the bed with even spacing.",
        intentKind="flanking",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="rug-under-bed",
        label="Rug extends under the bed",
        description="Slides a rug beneath the bed while keeping the walking areas usable.",
        intentKind="adjacent_to",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="floor-lamp",
        label="Floor lamp beside the bed",
        description="Sets a standing lamp on the floor beside the bed.",
        intentKind="adjacent_to",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="relative-chain",
        label="Bedside grouping",
        description="Places a nightstand beside the bed, then a lamp in front of the nightstand.",
        intentKind="adjacent_to",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="complete-bedroom",
        label="Complete bedroom arrangement",
        description="Shows the bed with two nightstands, a facing chair, an under-bed rug and a floor lamp.",
        intentKind="adjacent_to",
        expectedOutcome="solved",
    ),
    DesignFixture(
        id="missing-relative-reference",
        label="Missing related furniture",
        description="Shows why furniture cannot be placed relative to an arrangement that is missing.",
        intentKind="adjacent_to",
        expectedOutcome="failed",
    ),
    DesignFixture(
        id="relative-cycle",
        label="Furniture dependency loop",
        description="Shows why two pieces cannot each depend on the other being placed first.",
        intentKind="adjacent_to",
        expectedOutcome="failed",
    ),
    DesignFixture(
        id="malformed-flanking",
        label="Incomplete flanking pair",
        description="Shows why flanking needs one evenly spaced nightstand on each side.",
        intentKind="flanking",
        expectedOutcome="failed",
    ),
    DesignFixture(
        id="furniture-negative-gap",
        label="Furniture overlap not allowed",
        description="Shows why two ordinary pieces of furniture cannot occupy the same floor space.",
        intentKind="adjacent_to",
        expectedOutcome="failed",
    ),
)

_FIXTURE_INTENTS = {
    "against-wall": ({
        "id": "bed-against-north",
        "kind": "against",
        "productId": FEATURED_PRODUCT_ID,
        "wallId": "wall-north",
        "face": "back",
    },),
    "centred-on-wall": ({
        "id": "dresser-centred-south",
        "kind": "centred_on",
        "productId": "dresser-stylistics-campaign-white",
        "wallId": "wall-south",
        "face": "back",
    },),
    "in-corner": ({
        "id": "nightstand-north-west",
        "kind": "in_corner",
        "productId": "nightstand-alkove-hayes-wild-oak",
        "wallId": "wall-north",
        "adjacentWallId": "wall-west",
        "face": "back",
    },),
    "door-swing-failure": ({
        "id": "blocked-nightstand",
        "kind": "in_corner",
        "productId": "nightstand-alkove-hayes-wild-oak",
        "wallId": "wall-north",
        "adjacentWallId": "wall-east",
        "face": "back",
    },),
    "matching-nightstands": (
        {
            "id": "matching-nightstand-north",
            "kind": "centred_on",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "wallId": "wall-north",
            "face": "back",
        },
        {
            "id": "matching-nightstand-south",
            "kind": "centred_on",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "wallId": "wall-south",
            "face": "back",
        },
    ),
    "adjacent-nightstand": (
        {"id": "adjacent-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "adjacent-nightstand-right", "kind": "adjacent_to", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "adjacent-bed", "side": "right", "gapM": 0.6},
    ),
    "facing-chair": (
        {"id": "facing-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "chair-facing-bed", "kind": "facing", "productId": "chair-stone-beam-deco-wingback-walnut", "referenceId": "facing-bed", "gapM": 0.8},
    ),
    "flanking-nightstands": (
        {"id": "flanked-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "left-flank", "kind": "flanking", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "flanked-bed", "side": "left", "gapM": 1.0},
        {"id": "right-flank", "kind": "flanking", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "flanked-bed", "side": "right", "gapM": 1.0},
    ),
    "rug-under-bed": (
        {"id": "rug-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "under-bed-rug", "kind": "adjacent_to", "productId": "rug-rivet-arrow-black-ivory", "referenceId": "rug-bed", "side": "front", "gapM": -1.6},
    ),
    "floor-lamp": (
        {"id": "lamp-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "standing-lamp", "kind": "adjacent_to", "productId": "lamp-rivet-harper-brass", "referenceId": "lamp-bed", "side": "right", "gapM": 0.8},
    ),
    "relative-chain": (
        {"id": "chain-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "chain-nightstand", "kind": "adjacent_to", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "chain-bed", "side": "right", "gapM": 0.6},
        {"id": "chain-lamp", "kind": "adjacent_to", "productId": "lamp-rivet-harper-brass", "referenceId": "chain-nightstand", "side": "front", "gapM": 0.55},
    ),
    "complete-bedroom": (
        {"id": "complete-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "complete-left-nightstand", "kind": "flanking", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "complete-bed", "side": "left", "gapM": 0.7},
        {"id": "complete-right-nightstand", "kind": "flanking", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "complete-bed", "side": "right", "gapM": 0.7},
        {"id": "complete-chair", "kind": "facing", "productId": "chair-stone-beam-deco-wingback-walnut", "referenceId": "complete-bed", "gapM": 0.8},
        {"id": "complete-rug", "kind": "adjacent_to", "productId": "rug-rivet-arrow-black-ivory", "referenceId": "complete-bed", "side": "front", "gapM": -1.6},
        {"id": "complete-lamp", "kind": "adjacent_to", "productId": "lamp-rivet-harper-brass", "referenceId": "complete-left-nightstand", "side": "left", "gapM": 0.4},
    ),
    "missing-relative-reference": ({
        "id": "missing-relative",
        "kind": "adjacent_to",
        "productId": "nightstand-alkove-hayes-wild-oak",
        "referenceId": "not-a-request",
        "side": "right",
        "gapM": 0.6,
    },),
    "relative-cycle": (
        {"id": "cycle-a", "kind": "adjacent_to", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "cycle-b", "side": "left", "gapM": 0.6},
        {"id": "cycle-b", "kind": "adjacent_to", "productId": "nightstand-hallowood-waverly-light-oak", "referenceId": "cycle-a", "side": "right", "gapM": 0.6},
    ),
    "malformed-flanking": (
        {"id": "malformed-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "only-left-flank", "kind": "flanking", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "malformed-bed", "side": "left", "gapM": 0.6},
    ),
    "furniture-negative-gap": (
        {"id": "overlap-bed", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"},
        {"id": "overlap-nightstand", "kind": "adjacent_to", "productId": "nightstand-alkove-hayes-wild-oak", "referenceId": "overlap-bed", "side": "right", "gapM": -0.1},
    ),
}

_OBJECT_FIXTURES = frozenset({
    "adjacent-nightstand",
    "facing-chair",
    "flanking-nightstands",
    "rug-under-bed",
    "floor-lamp",
    "relative-chain",
    "complete-bedroom",
    "missing-relative-reference",
    "relative-cycle",
    "malformed-flanking",
    "furniture-negative-gap",
})


def design_fixtures() -> DesignFixtures:
    return DesignFixtures(fixtures=_FIXTURES)


def resolve_fixture(selection: FixtureSelectionRequest, source: Catalogue = catalogue) -> DesignResultValue:
    intents = _FIXTURE_INTENTS.get(selection.fixtureId)
    if intents is None:
        return DesignFailure(
            status="failed",
            reason="unknown-fixture-reference",
            detail=f'No visible bedroom fixture has id "{selection.fixtureId}"',
            failedIntentId="",
            search=SearchReport(
                attemptedCandidates=0,
                candidateLimit=selection.maxCandidates,
                exhaustive=True,
            ),
        )
    request = DesignRequest.model_validate({
        "room": (
            object_intent_fixture_room()
            if selection.fixtureId in _OBJECT_FIXTURES
            else intent_fixture_room()
        ).model_dump(mode="json"),
        "intents": intents,
        "maxCandidates": selection.maxCandidates,
    })
    return resolve_design(source, request)
