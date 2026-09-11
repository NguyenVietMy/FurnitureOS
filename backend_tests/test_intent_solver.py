from __future__ import annotations

from copy import deepcopy
from math import pi, sqrt

import pytest
from pydantic import ValidationError

from api.catalogue import CatalogueEntry, StaticCatalogue, catalogue
from api.design import FEATURED_PRODUCT_ID, bedroom_room_shell
from api.domain import resolve_design, validate_placement
from api.models import DesignRequest, Placement, Product, RoomShell


def product_variant(
    product: Product,
    product_id: str,
    *,
    width: float,
    depth: float,
    height: float = 1.0,
    contact_faces: list[str] | None = None,
    access_regions: list[dict] | None = None,
) -> Product:
    value = deepcopy(product.model_dump(mode="json"))
    value.update({
        "id": product_id,
        "displayName": product_id,
        "dimensionsM": {"widthM": width, "heightM": height, "depthM": depth},
        "accessRegions": access_regions or [],
    })
    if contact_faces is not None:
        value["wallContactFaces"] = contact_faces
    return Product.model_validate(value)


def make_catalogue(*products: Product) -> StaticCatalogue:
    return StaticCatalogue("solver-test", [
        CatalogueEntry(product=product, private_style_ids=("fixture-style",))
        for product in products
    ])


def polygon_room(points: list[tuple[float, float]], wall_ids: list[str]) -> RoomShell:
    return RoomShell.model_validate({
        "id": "hand-worked-room",
        "floorPolygon": points,
        "ceilingHeightM": 2.5,
        "walls": [{
            "id": wall_id,
            "label": wall_id,
            "start": points[index],
            "end": points[(index + 1) % len(points)],
        } for index, wall_id in enumerate(wall_ids)],
    })


def test_centred_on_resolves_hand_worked_wall_geometry_without_coordinates() -> None:
    request = DesignRequest.model_validate({
        "room": bedroom_room_shell().model_dump(mode="json"),
        "intents": [{
            "id": "centre-bed",
            "kind": "centred_on",
            "productId": FEATURED_PRODUCT_ID,
            "wallId": "wall-north",
            "face": "back",
        }],
        "maxCandidates": 32,
    })

    result = resolve_design(catalogue, request)

    assert result.status == "solved"
    assert len(result.placements) == 1
    placement = result.placements[0]
    assert placement.productId == FEATURED_PRODUCT_ID
    assert placement.position == pytest.approx((0.0, 0.0, -0.383505), abs=1e-6)
    assert placement.yaw == pytest.approx(0.0, abs=1e-9)
    assert placement.wallContact is not None
    assert placement.wallContact.wallId == "wall-north"


def test_in_corner_uses_adjacent_reversed_diagonal_walls_and_literal_geometry(product: Product) -> None:
    small = product_variant(product, "square-table", width=0.5, depth=0.5, contact_faces=["back", "right"])
    diagonal_room = polygon_room(
        [(-sqrt(2), 0), (0, sqrt(2)), (sqrt(2), 0), (0, -sqrt(2))],
        ["primary", "next", "opposite", "adjacent-at-start"],
    )
    request = DesignRequest.model_validate({
        "room": diagonal_room.model_dump(mode="json"),
        "intents": [{
            "id": "corner-table",
            "kind": "in_corner",
            "productId": small.id,
            "wallId": "primary",
            "adjacentWallId": "adjacent-at-start",
            "face": "back",
        }],
    })

    result = resolve_design(make_catalogue(small), request)

    assert result.status == "solved"
    assert result.placements[0].position == pytest.approx((-1.060660172, 0.0, 0.0), abs=1e-8)
    assert result.placements[0].yaw == pytest.approx(3 * pi / 4, abs=1e-9)
    assert [contact.model_dump(mode="json") for contact in result.placements[0].wallContacts] == [
        {"wallId": "primary", "face": "back"},
        {"wallId": "adjacent-at-start", "face": "right"},
    ]


def test_in_corner_rejects_an_unauthorized_secondary_face(product: Product) -> None:
    back_only = product_variant(product, "back-only", width=0.5, depth=0.5, contact_faces=["back"])
    room = polygon_room(
        [(-2.0, -2.0), (-2.0, 2.0), (2.0, 2.0), (2.0, -2.0)],
        ["west", "south", "east", "north"],
    )

    result = resolve_design(make_catalogue(back_only), DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{
            "id": "north-west",
            "kind": "in_corner",
            "productId": back_only.id,
            "wallId": "north",
            "adjacentWallId": "west",
        }],
    }))

    assert result.status == "failed"
    assert result.reason == "product-face-not-supported"
    assert "left face" in result.detail
    assert result.search.attemptedCandidates == 0


def test_in_corner_rejects_a_non_right_angle_as_typed_unsupported_geometry(product: Product) -> None:
    corner_product = product_variant(
        product,
        "three-face-cabinet",
        width=0.5,
        depth=0.5,
        contact_faces=["back", "left", "right"],
    )
    triangle = polygon_room(
        [(0.0, -2.0), (1.732050808, 1.0), (-1.732050808, 1.0)],
        ["diagonal-east", "south", "diagonal-west"],
    )

    result = resolve_design(make_catalogue(corner_product), DesignRequest.model_validate({
        "room": triangle.model_dump(mode="json"),
        "intents": [{
            "id": "sixty-degree-corner",
            "kind": "in_corner",
            "productId": corner_product.id,
            "wallId": "diagonal-east",
            "adjacentWallId": "diagonal-west",
        }],
    }))

    assert result.status == "failed"
    assert result.reason == "corner-angle-not-supported"
    assert result.search.attemptedCandidates == 0


def test_in_corner_is_physically_identical_when_wall_segments_are_reversed(product: Product) -> None:
    cabinet = product_variant(
        product,
        "reversible-corner-cabinet",
        width=0.5,
        depth=0.5,
        contact_faces=["back", "left", "right"],
    )
    points = [(-2.0, -2.0), (-2.0, 2.0), (2.0, 2.0), (2.0, -2.0)]
    forward_room = polygon_room(points, ["west", "south", "east", "north"])
    reversed_value = forward_room.model_dump(mode="json")
    for wall in reversed_value["walls"]:
        wall["start"], wall["end"] = wall["end"], wall["start"]
    reversed_room = RoomShell.model_validate(reversed_value)

    def solve(room: RoomShell):
        return resolve_design(make_catalogue(cabinet), DesignRequest.model_validate({
            "room": room.model_dump(mode="json"),
            "intents": [{
                "id": "north-west-cabinet",
                "kind": "in_corner",
                "productId": cabinet.id,
                "wallId": "north",
                "adjacentWallId": "west",
            }],
        }))

    forward = solve(forward_room)
    reversed_walls = solve(reversed_room)

    assert forward.status == reversed_walls.status == "solved"
    assert reversed_walls.placements[0].position == pytest.approx(forward.placements[0].position, abs=1e-9)
    assert reversed_walls.placements[0].yaw == pytest.approx(forward.placements[0].yaw, abs=1e-9)
    assert reversed_walls.placements[0].wallContacts == forward.placements[0].wallContacts


def test_against_search_is_deterministic_and_reports_exhaustion_separately(product: Product) -> None:
    first = product_variant(product, "first-square", width=1.0, depth=1.0)
    second = product_variant(product, "second-square", width=1.0, depth=1.0)
    request_body = {
        "room": bedroom_room_shell().model_dump(mode="json"),
        "intents": [
            {"id": "fixed", "kind": "centred_on", "productId": first.id, "wallId": "wall-north"},
            {"id": "searching", "kind": "against", "productId": second.id, "wallId": "wall-north"},
        ],
        "maxCandidates": 64,
    }
    source = make_catalogue(first, second)

    result = resolve_design(source, DesignRequest.model_validate(request_body))
    repeated = resolve_design(source, DesignRequest.model_validate(request_body))

    assert result.status == repeated.status == "solved"
    assert result.model_dump_json() == repeated.model_dump_json()
    assert result.placements[0].position == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)
    assert result.placements[1].position == pytest.approx((1.0, 0.0, -1.0), abs=1e-9)

    request_body["maxCandidates"] = 2
    exhausted = resolve_design(source, DesignRequest.model_validate(request_body))
    assert exhausted.status == "failed"
    assert exhausted.reason == "search-exhausted"
    assert exhausted.failedIntentId == "searching"
    assert exhausted.search.attemptedCandidates == 2
    assert exhausted.search.exhaustive is False


def test_backtracking_revisits_an_earlier_against_placement_for_a_known_fit(product: Product) -> None:
    first = product_variant(product, "movable-first", width=1.0, depth=1.0)
    second = product_variant(product, "fixed-second", width=1.0, depth=1.0)
    room = polygon_room(
        [(-2.0, -2.0), (-2.0, 2.0), (2.0, 2.0), (2.0, -2.0)],
        ["west", "south", "east", "north"],
    )
    request = DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [
            {"id": "movable", "kind": "against", "productId": first.id, "wallId": "north"},
            {"id": "fixed", "kind": "centred_on", "productId": second.id, "wallId": "north"},
        ],
        "maxCandidates": 128,
    })

    result = resolve_design(make_catalogue(first, second), request)

    assert result.status == "solved"
    assert result.placements[0].position == pytest.approx((-1.0, 0.0, -1.5), abs=1e-9)
    assert result.placements[1].position == pytest.approx((0.0, 0.0, -1.5), abs=1e-9)
    # Independent graph-ready requests are solved by stable request id, so
    # reordering the public array cannot change which geometry is chosen.
    assert result.search.attemptedCandidates == 21


def test_full_discrete_against_grid_does_not_claim_continuous_exhaustiveness(product: Product) -> None:
    needs_too_much_access = product_variant(
        product,
        "continuous-grid-failure",
        width=0.5,
        depth=0.5,
        access_regions=[{
            "face": "front",
            "depthM": 3.0,
            "required": True,
            "purpose": "opening the cabinet",
        }],
    )
    room = polygon_room(
        [(-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)],
        ["west", "south", "east", "north"],
    )

    result = resolve_design(make_catalogue(needs_too_much_access), DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{
            "id": "search-entire-grid",
            "kind": "against",
            "productId": needs_too_much_access.id,
            "wallId": "north",
        }],
        "maxCandidates": 128,
    }))

    assert result.status == "failed"
    assert result.reason == "search-exhausted"
    assert result.search.attemptedCandidates == 17
    assert result.search.exhaustive is False


def test_repeated_product_references_publish_stable_intent_instance_ids(product: Product) -> None:
    matching = product_variant(product, "matching-nightstand", width=0.5, depth=0.5)
    room = polygon_room(
        [(-3.0, -3.0), (-3.0, 3.0), (3.0, 3.0), (3.0, -3.0)],
        ["west", "south", "east", "north"],
    )
    request = DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [
            {"id": "matching-north", "kind": "centred_on", "productId": matching.id, "wallId": "north"},
            {"id": "matching-south", "kind": "centred_on", "productId": matching.id, "wallId": "south"},
        ],
    })

    result = resolve_design(make_catalogue(matching), request)

    assert result.status == "solved"
    assert [product.id for product in result.products] == [matching.id, matching.id]
    assert [placement.instanceId for placement in result.placements] == ["matching-north", "matching-south"]
    assert result.placements[0].position == pytest.approx((0.0, 0.0, -2.75), abs=1e-9)
    assert result.placements[1].position == pytest.approx((0.0, 0.0, 2.75), abs=1e-9)


def test_opening_height_interval_blocks_tall_product_but_not_low_product(product: Product) -> None:
    room_value = bedroom_room_shell().model_dump(mode="json")
    room_value["openings"] = [{
        "id": "north-window",
        "kind": "window",
        "wallId": "wall-north",
        "offsetAlongWallM": 0.0,
        "widthM": 1.5,
        "bottomM": 1.2,
        "heightM": 1.0,
        "clearanceDepthM": 0.4,
    }]
    room = RoomShell.model_validate(room_value)
    low = product_variant(product, "low-console", width=1.0, depth=0.5, height=1.0)
    tall = product_variant(product, "tall-cabinet", width=1.0, depth=0.5, height=1.5)

    low_result = resolve_design(make_catalogue(low), DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{"id": "below-window", "kind": "centred_on", "productId": low.id, "wallId": "wall-north"}],
    }))
    tall_result = resolve_design(make_catalogue(tall), DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{"id": "through-window", "kind": "centred_on", "productId": tall.id, "wallId": "wall-north"}],
    }))

    assert low_result.status == "solved"
    assert tall_result.status == "failed"
    assert tall_result.reason == "opening-exclusion"
    assert "north-window" in tall_result.detail


def test_inward_quarter_circle_door_swing_blocks_corner_placement(product: Product) -> None:
    room_value = bedroom_room_shell().model_dump(mode="json")
    room_value["openings"] = [{
        "id": "north-west-door",
        "kind": "door",
        "wallId": "wall-north",
        "offsetAlongWallM": -1.55,
        "widthM": 0.9,
        "bottomM": 0.0,
        "heightM": 2.1,
        "clearanceDepthM": 0.0,
        "doorSwing": {"hingeSide": "start"},
    }]
    room = RoomShell.model_validate(room_value)
    table = product_variant(
        product,
        "corner-table",
        width=0.5,
        depth=0.5,
        contact_faces=["back", "left", "right"],
    )

    result = resolve_design(make_catalogue(table), DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{
            "id": "door-corner",
            "kind": "in_corner",
            "productId": table.id,
            "wallId": "wall-north",
            "adjacentWallId": "wall-west",
        }],
    }))

    assert result.status == "failed"
    assert result.reason == "door-swing-exclusion"
    assert "north-west-door" in result.detail


def test_door_swing_conservatively_covers_the_true_arc_between_samples(product: Product) -> None:
    room_value = bedroom_room_shell().model_dump(mode="json")
    room_value["openings"] = [{
        "id": "arc-door",
        "kind": "door",
        "wallId": "wall-north",
        "offsetAlongWallM": 0.5,
        "widthM": 1.0,
        "bottomM": 0.0,
        "heightM": 2.1,
        "clearanceDepthM": 0.0,
        "doorSwing": {"hingeSide": "start"},
    }]
    room = RoomShell.model_validate(room_value)
    edge_crossing = product_variant(
        product,
        "near-arc-edge-crossing",
        width=0.02,
        depth=0.004,
    )
    # Literal point on the true r=1 m arc halfway between two 16-segment
    # samples. An inscribed chord is 1.205 mm inside the arc here.
    candidate = Placement(
        productId=edge_crossing.id,
        position=(0.998795456, 0.0, -1.450932326),
        yaw=1.521708942,
        wallContact=None,
    )

    result = validate_placement(edge_crossing, room, candidate)

    assert result.status == "invalid-fit"
    assert result.reason == "door-swing-exclusion"


def test_selected_face_rotates_a_non_square_footprint_against_a_diagonal_wall(product: Product) -> None:
    cabinet = product_variant(
        product,
        "side-contact-cabinet",
        width=1.2,
        depth=0.4,
        contact_faces=["right"],
    )
    diagonal_room = polygon_room(
        [(-sqrt(2), 0), (0, sqrt(2)), (sqrt(2), 0), (0, -sqrt(2))],
        ["primary", "next", "opposite", "previous"],
    )

    result = resolve_design(make_catalogue(cabinet), DesignRequest.model_validate({
        "room": diagonal_room.model_dump(mode="json"),
        "intents": [{
            "id": "rotated-cabinet",
            "kind": "centred_on",
            "productId": cabinet.id,
            "wallId": "primary",
            "face": "right",
        }],
    }))

    assert result.status == "solved"
    assert result.placements[0].position == pytest.approx((-0.282842712, 0.0, 0.282842712), abs=1e-8)
    assert result.placements[0].yaw == pytest.approx(5 * pi / 4, abs=1e-9)


def test_required_access_remains_free_of_every_other_product(product: Product) -> None:
    accessible = product_variant(
        product,
        "accessible-cabinet",
        width=0.5,
        depth=0.5,
        access_regions=[{
            "face": "front",
            "depthM": 1.5,
            "required": True,
            "purpose": "opening the cabinet",
        }],
    )
    blocker = product_variant(product, "blocking-cabinet", width=0.5, depth=0.5)
    small_room = polygon_room(
        [(-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)],
        ["wall-west", "wall-south", "wall-east", "wall-north"],
    )

    result = resolve_design(make_catalogue(accessible, blocker), DesignRequest.model_validate({
        "room": small_room.model_dump(mode="json"),
        "intents": [
            {"id": "needs-access", "kind": "centred_on", "productId": accessible.id, "wallId": "wall-north"},
            {"id": "blocks-access", "kind": "centred_on", "productId": blocker.id, "wallId": "wall-south"},
        ],
    }))

    assert result.status == "failed"
    assert result.reason == "access-region-blocked"
    # Stable id ordering places blocks-access first; needs-access is the
    # candidate whose own required region then detects that obstruction.
    assert result.failedIntentId == "needs-access"


def test_required_access_cannot_occupy_a_door_swing(product: Product) -> None:
    room = polygon_room(
        [(-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)],
        ["west", "south", "east", "north"],
    )
    room_value = room.model_dump(mode="json")
    room_value["openings"] = [{
        "id": "north-door",
        "kind": "door",
        "wallId": "north",
        "offsetAlongWallM": 0.0,
        "widthM": 1.0,
        "bottomM": 0.0,
        "heightM": 2.1,
        "clearanceDepthM": 0.0,
        "doorSwing": {"hingeSide": "start"},
    }]
    room = RoomShell.model_validate(room_value)
    cabinet = product_variant(
        product,
        "south-cabinet",
        width=0.5,
        depth=0.2,
        access_regions=[{
            "face": "front",
            "depthM": 1.8,
            "required": True,
            "purpose": "opening the cabinet",
        }],
    )

    result = resolve_design(make_catalogue(cabinet), DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{"id": "south-access", "kind": "centred_on", "productId": cabinet.id, "wallId": "south"}],
    }))

    assert result.status == "failed"
    assert result.reason == "access-region-blocked"
    assert "north-door" in result.detail


@pytest.mark.parametrize(
    "intents,reason",
    [
        ([{"id": "bad-kind", "kind": "floating", "productId": "known", "wallId": "wall-north"}], "unsupported-intent"),
        ([{"id": "no-surface-placement", "kind": "on_surface", "productId": "known"}], "unsupported-intent"),
        ([{"id": "unknown-product", "kind": "against", "productId": "missing", "wallId": "wall-north"}], "unknown-product-reference"),
        ([{"id": "unknown-wall", "kind": "against", "productId": "known", "wallId": "missing"}], "unknown-wall-reference"),
        ([{"id": "bad-face", "kind": "against", "productId": "known", "wallId": "wall-north", "face": "front"}], "product-face-not-supported"),
        ([{"id": "not-a-corner", "kind": "in_corner", "productId": "known", "wallId": "wall-north", "adjacentWallId": "wall-south"}], "nonadjacent-corner-walls"),
        ([
            {"id": "duplicate", "kind": "centred_on", "productId": "known", "wallId": "wall-north"},
            {"id": "duplicate", "kind": "centred_on", "productId": "second", "wallId": "wall-south"},
        ], "duplicate-intent-reference"),
    ],
)
def test_invalid_intent_and_reference_cases_return_typed_failures(product: Product, intents: list[dict], reason: str) -> None:
    known = product_variant(product, "known", width=0.5, depth=0.5)
    second = product_variant(product, "second", width=0.5, depth=0.5)
    result = resolve_design(make_catalogue(known, second), DesignRequest.model_validate({
        "room": bedroom_room_shell().model_dump(mode="json"),
        "intents": intents,
    }))
    assert result.status == "failed"
    assert result.reason == reason
    assert not hasattr(result, "placements")


@pytest.mark.parametrize("mutation", ["unknown-wall", "outside-wall", "duplicate-id", "window-swing"])
def test_room_rejects_invalid_opening_geometry(mutation: str) -> None:
    room_value = bedroom_room_shell().model_dump(mode="json")
    opening = {
        "id": "opening-a",
        "kind": "window",
        "wallId": "wall-north",
        "offsetAlongWallM": 0.0,
        "widthM": 1.0,
        "bottomM": 1.0,
        "heightM": 1.0,
        "clearanceDepthM": 0.3,
    }
    room_value["openings"] = [opening]
    if mutation == "unknown-wall":
        opening["wallId"] = "missing"
    elif mutation == "outside-wall":
        opening["offsetAlongWallM"] = 2.0
        opening["widthM"] = 1.0
    elif mutation == "duplicate-id":
        room_value["openings"].append(dict(opening))
    else:
        opening["doorSwing"] = {"hingeSide": "start"}

    with pytest.raises(ValidationError):
        RoomShell.model_validate(room_value)
