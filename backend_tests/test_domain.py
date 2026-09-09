from __future__ import annotations

from copy import deepcopy
from math import pi

import pytest
from pydantic import ValidationError

from api.domain import (
    DEFAULT_TOLERANCES, access_footprint, face_normal, get_wall, inside_depth,
    place_against_wall, rectangular_room_shell, validate_placement, wall_facing_yaw,
    yaw_to_forward,
)
from api.models import AccessRegion, Placement, Product, RoomShell


def variant(product: Product, **updates) -> Product:
    value = deepcopy(product.model_dump(mode="json"))
    value.update(updates)
    return Product.model_validate(value)


def placement(product: Product, x=0.0, y=0.0, z=0.0, yaw=0.0, contact=None) -> Placement:
    return Placement(productId=product.id, position=(x, y, z), yaw=yaw, wallContact=contact)


def shell(points, ids=None, ceiling=2.5) -> RoomShell:
    ids = ids or [f"edge-{index}" for index in range(len(points))]
    walls = [
        {"id": ids[index], "label": ids[index], "start": points[index], "end": points[(index + 1) % len(points)]}
        for index in range(len(points))
    ]
    return RoomShell.model_validate({"id": "polygon-room", "floorPolygon": points, "walls": walls, "ceilingHeightM": ceiling})


@pytest.mark.parametrize("yaw,expected", [(0, (0, 1)), (pi / 2, (1, 0)), (pi, (0, -1)), (-pi / 2, (-1, 0))])
def test_yaw_uses_the_canonical_plus_z_front(yaw, expected) -> None:
    assert yaw_to_forward(yaw) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("face,expected", [
    ("front", (0, 1)), ("back", (0, -1)), ("right", (1, 0)), ("left", (-1, 0)),
])
def test_face_normals_follow_product_orientation(face, expected) -> None:
    assert face_normal(face, 0) == expected


def test_rectangular_room_has_stable_wall_ids(room) -> None:
    assert [wall.id for wall in room.walls] == ["wall-north", "wall-east", "wall-south", "wall-west"]


@pytest.mark.parametrize("wall_id,expected_yaw", [
    ("wall-north", 0), ("wall-east", -pi / 2), ("wall-south", pi), ("wall-west", pi / 2),
])
def test_every_wall_faces_products_into_the_room(room, wall_id, expected_yaw) -> None:
    assert wall_facing_yaw(room, get_wall(room, wall_id)) == pytest.approx(expected_yaw, abs=1e-9)


@pytest.mark.parametrize("wall_id", ["wall-north", "wall-east", "wall-south", "wall-west"])
def test_curated_product_places_against_every_wall(product, room, wall_id) -> None:
    result = place_against_wall(product, room, wall_id)
    assert result.status == "fits"
    assert result.placement.wallContact.wallId == wall_id
    assert result.measurements.wallGapM == pytest.approx(0, abs=1e-9)


def test_wall_placement_is_deterministic(product, room) -> None:
    first = place_against_wall(product, room, "wall-north")
    second = place_against_wall(product, room, "wall-north")
    assert first.model_dump_json() == second.model_dump_json()


def test_offset_slides_along_the_wall(product, room) -> None:
    result = place_against_wall(product, room, "wall-north", offset_along_wall_m=0.5)
    assert result.status == "fits"
    assert result.placement.position[0] == pytest.approx(0.5)


def test_large_offset_reports_footprint_overhang(product, room) -> None:
    result = place_against_wall(product, room, "wall-north", offset_along_wall_m=1.5)
    assert result.status == "invalid-fit"
    assert result.reason == "footprint-outside-room"


def test_oversized_product_reports_room_bounds(product, room) -> None:
    oversized = variant(
        product,
        id="bed-oversized-fixture",
        dimensionsM={"widthM": 4.5, "heightM": 1.4, "depthM": 3.5},
        accessRegions=[{"face": "front", "depthM": 0.6, "required": True, "purpose": "walking past the foot"}],
    )
    result = place_against_wall(oversized, room, "wall-north")
    assert result.status == "invalid-fit"
    assert result.reason == "product-exceeds-room-bounds"
    assert result.productId == "bed-oversized-fixture"
    assert result.roomId == room.id
    assert "does not fit inside" in result.detail
    assert result.measurements.clearanceM < 0


def test_shallow_room_reports_required_front_access(product) -> None:
    shallow = rectangular_room_shell("shallow", 4, 2.6, 2.5)
    result = place_against_wall(product, shallow, "wall-north")
    assert result.status == "invalid-fit"
    assert result.reason == "access-region-outside-room"
    assert "walking past the foot" in result.detail


def test_forbidden_contact_face_is_a_typed_invalid_fit(product, room) -> None:
    result = place_against_wall(product, room, "wall-north", "front")
    assert result.status == "invalid-fit"
    assert result.reason == "wall-contact-face-not-allowed"


@pytest.mark.parametrize("gap,status", [
    (DEFAULT_TOLERANCES.wall_contact_m / 2, "fits"),
    (DEFAULT_TOLERANCES.wall_contact_m * 2, "invalid-fit"),
])
def test_wall_gap_tolerance_is_explicit(product, room, gap, status) -> None:
    z = -1.5 + product.dimensionsM.depthM / 2 + gap
    result = validate_placement(product, room, placement(product, z=z, contact={"wallId": "wall-north", "face": "back"}))
    assert result.status == status
    if status == "invalid-fit":
        assert result.reason == "not-touching-declared-wall"


def test_non_floor_product_cannot_use_floor_placement(product, room) -> None:
    shelf = variant(product, id="shelf", placementClass="wall-mounted")
    result = validate_placement(shelf, room, placement(shelf))
    assert result.status == "invalid-fit"
    assert result.reason == "placement-class-cannot-stand-on-floor"


def test_product_top_cannot_cross_the_ceiling(product, room) -> None:
    result = validate_placement(product, room, placement(product, y=1.1))
    assert result.status == "invalid-fit"
    assert result.reason == "not-resting-on-floor"
    low_ceiling = rectangular_room_shell("low", 4, 3, 1.4)
    result = validate_placement(product, low_ceiling, placement(product))
    assert result.status == "invalid-fit"
    assert result.reason == "exceeds-ceiling-height"


@pytest.mark.parametrize("face,room_size", [
    ("right", (2.6, 4.0)), ("left", (2.6, 4.0)),
    ("front", (4.0, 2.6)), ("back", (4.0, 2.6)),
])
def test_access_region_uses_the_selected_face_axis(product, face, room_size) -> None:
    access_product = variant(
        product, id=f"access-{face}", dimensionsM={"widthM": 1.0, "heightM": 1.0, "depthM": 0.4},
        accessRegions=[{"face": face, "depthM": 1.2, "required": True, "purpose": "independent access"}],
    )
    test_room = rectangular_room_shell("access-room", room_size[0], room_size[1], 2.5)
    result = validate_placement(access_product, test_room, placement(access_product))
    assert result.status == "invalid-fit"
    assert result.reason == "access-region-outside-room"


def test_right_access_regression_spans_the_side_face_exactly(product) -> None:
    access_product = variant(
        product, id="side-access", dimensionsM={"widthM": 1.0, "heightM": 1.0, "depthM": 0.4},
        accessRegions=[{"face": "right", "depthM": 1.0, "required": True, "purpose": "side access"}],
    )
    region = access_footprint(access_product, AccessRegion(face="right", depthM=1.0, required=True, purpose="side access"), (0, 0), 0)
    assert region.widthM == pytest.approx(0.4)
    assert region.depthM == pytest.approx(1.0)
    assert max(point[0] for point in region.corners) == pytest.approx(1.5)
    result = validate_placement(access_product, rectangular_room_shell("narrow", 2.6, 4, 2.5), placement(access_product))
    assert result.status == "invalid-fit"


def test_rotated_side_access_rotates_with_the_product(product) -> None:
    access_product = variant(
        product, id="rotated-access", dimensionsM={"widthM": 1.0, "heightM": 1.0, "depthM": 0.4},
        accessRegions=[{"face": "right", "depthM": 1.0, "required": True, "purpose": "side access"}],
    )
    result = validate_placement(access_product, rectangular_room_shell("shallow", 4, 2.6, 2.5), placement(access_product, yaw=pi / 2))
    assert result.status == "invalid-fit"
    assert result.reason == "access-region-outside-room"


def test_optional_access_does_not_block_fit(product) -> None:
    access_product = variant(
        product, id="optional-access", dimensionsM={"widthM": 1.0, "heightM": 1.0, "depthM": 0.4},
        accessRegions=[{"face": "right", "depthM": 10, "required": False, "purpose": "optional"}],
    )
    assert validate_placement(access_product, rectangular_room_shell("room", 2, 2, 2.5), placement(access_product)).status == "fits"


def test_convex_room_shell_supports_more_than_four_walls(product) -> None:
    polygon = shell([(-2, -1), (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1)])
    small = variant(product, id="chair", dimensionsM={"widthM": 0.5, "heightM": 1, "depthM": 0.5}, accessRegions=[])
    assert validate_placement(small, polygon, placement(small)).status == "fits"
    assert inside_depth(polygon, (0, 0)) > 0


def test_arbitrary_stable_wall_id_resolves(product) -> None:
    points = [(-2, -1.5), (-2, 1.5), (2, 1.5), (2, -1.5)]
    custom = shell(points, ["capture-a", "capture-b", "capture-c", "headboard-wall"])
    result = place_against_wall(product, custom, "headboard-wall")
    assert result.status == "fits"
    assert result.placement.wallContact.wallId == "headboard-wall"


def test_short_wall_is_reported_before_generic_overhang(product) -> None:
    trapezoid = shell([(-2, -1), (-1.5, 1), (1.5, 1), (2, -1)], ["west", "short-edge", "east", "long-edge"])
    wide = variant(product, id="wide", dimensionsM={"widthM": 3.5, "heightM": 1, "depthM": 0.4}, accessRegions=[])
    result = place_against_wall(wide, trapezoid, "short-edge")
    assert result.status == "invalid-fit"
    assert result.reason == "wall-shorter-than-product"


@pytest.mark.parametrize("width,depth,height", [(0, 3, 2.5), (-1, 3, 2.5), (4, 0, 2.5), (4, 3, 0), (float("nan"), 3, 2.5)])
def test_rectangular_room_rejects_invalid_dimensions(width, depth, height) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        rectangular_room_shell("bad", width, depth, height)


@pytest.mark.parametrize("mutation", ["duplicate-point", "duplicate-wall", "missing-edge", "concave"])
def test_room_shell_rejects_invalid_topology(mutation) -> None:
    points = [[-1, -1], [-1, 1], [1, 1], [1, -1]]
    walls = [
        {"id": f"wall-{index}", "label": f"Wall {index}", "start": points[index], "end": points[(index + 1) % 4]}
        for index in range(4)
    ]
    if mutation == "duplicate-point":
        points[2] = points[1]
    elif mutation == "duplicate-wall":
        walls[1]["id"] = walls[0]["id"]
    elif mutation == "missing-edge":
        walls[1]["end"] = points[3]
    else:
        points[2] = [0, 0]
        walls = [{"id": f"wall-{index}", "label": f"Wall {index}", "start": points[index], "end": points[(index + 1) % 4]} for index in range(4)]
    with pytest.raises(ValidationError):
        RoomShell.model_validate({"id": "bad", "floorPolygon": points, "walls": walls, "ceilingHeightM": 2.5})
