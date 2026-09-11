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
}


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
        "room": intent_fixture_room().model_dump(mode="json"),
        "intents": intents,
        "maxCandidates": selection.maxCandidates,
    })
    return resolve_design(source, request)
