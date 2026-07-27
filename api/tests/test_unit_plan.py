"""The unit plan schema is the contract every downstream slice reads.

Issue 01 locks this shape: outer polygon, interior partition walls, named room
regions, wall openings, ceiling height. Getting it wrong here is expensive later,
so the invariants are pinned by test rather than by convention.
"""

import copy
from typing import Any

import pytest

from furnitureos.modules.units import UnitPlanError, load_seed_unit, parse_unit_plan


@pytest.fixture
def valid_plan() -> dict[str, Any]:
    """A deep copy of the seeded placeholder unit, safe for tests to mutate."""
    return copy.deepcopy(load_seed_unit("sunrise-b").raw)


def rectangular_plan(outline: list[list[float]]) -> dict[str, Any]:
    """A minimal internally-consistent plan whose single room fills the outline.

    Area tests need to vary the outline. Mutating the seed's outline while leaving its
    rooms behind would trip containment first and never reach the area calculation, so
    they get a purpose-built plan instead.
    """
    return {
        "slug": "test-unit",
        "name": "Test",
        "building": "Test",
        "ceiling_height_m": 2.7,
        "outline": outline,
        "partitions": [],
        "rooms": [{"key": "only", "name": "Only", "type": "living", "polygon": outline}],
        "openings": [],
    }


def test_parses_the_seeded_placeholder_unit() -> None:
    plan = load_seed_unit("sunrise-b")

    assert plan.slug == "sunrise-b"
    assert plan.ceiling_height_m > 2.0
    assert len(plan.outline) >= 3
    assert len(plan.rooms) >= 3
    assert plan.openings, "the seed must exercise openings, they are part of the schema"


def test_outline_is_not_rectangular() -> None:
    """The placeholder must exercise non-rectangular geometry.

    A rectangle would let axis-aligned assumptions survive into issue 03, which is
    exactly the bug this project is trying not to inherit from the prototype.
    """
    plan = load_seed_unit("sunrise-b")

    xs = {round(x, 3) for x, _ in plan.outline}
    ys = {round(y, 3) for _, y in plan.outline}

    assert len(plan.outline) > 4 or len(xs) > 2 or len(ys) > 2


def test_area_is_computed_from_the_outline() -> None:
    """Area is derived, never stored â€” one source of truth (issue 02 depends on this)."""
    plan = rectangular_plan([[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]])

    assert parse_unit_plan(plan).area_m2 == pytest.approx(12.0)


def test_area_is_orientation_independent() -> None:
    """Shoelace is signed; area must not be. Traced outlines can wind either way."""
    clockwise = rectangular_plan([[0.0, 0.0], [0.0, 3.0], [4.0, 3.0], [4.0, 0.0]])

    assert parse_unit_plan(clockwise).area_m2 == pytest.approx(12.0)


def test_area_of_the_l_shaped_seed_is_not_its_bounding_box() -> None:
    """Pins the seed's real area, and proves the notch is actually subtracted."""
    plan = load_seed_unit("sunrise-b")

    assert plan.area_m2 == pytest.approx(74.0)
    bounding_box = (max(x for x, _ in plan.outline) - min(x for x, _ in plan.outline)) * (
        max(y for _, y in plan.outline) - min(y for _, y in plan.outline)
    )
    assert plan.area_m2 < bounding_box


def test_bedroom_count_is_derived_from_room_types(valid_plan: dict[str, Any]) -> None:
    assert parse_unit_plan(valid_plan).bedrooms == sum(
        1 for room in valid_plan["rooms"] if room["type"] == "bedroom"
    )


def test_rejects_outline_with_fewer_than_three_points(valid_plan: dict[str, Any]) -> None:
    valid_plan["outline"] = [[0.0, 0.0], [4.0, 0.0]]

    with pytest.raises(UnitPlanError, match="outline"):
        parse_unit_plan(valid_plan)


def test_rejects_non_positive_ceiling_height(valid_plan: dict[str, Any]) -> None:
    valid_plan["ceiling_height_m"] = 0.0

    with pytest.raises(UnitPlanError, match="ceiling"):
        parse_unit_plan(valid_plan)


def test_rejects_duplicate_room_keys(valid_plan: dict[str, Any]) -> None:
    valid_plan["rooms"].append(copy.deepcopy(valid_plan["rooms"][0]))

    with pytest.raises(UnitPlanError, match="room key"):
        parse_unit_plan(valid_plan)


def test_rejects_room_polygon_outside_the_outline(valid_plan: dict[str, Any]) -> None:
    valid_plan["rooms"][0]["polygon"] = [
        [900.0, 900.0],
        [903.0, 900.0],
        [903.0, 903.0],
        [900.0, 903.0],
    ]

    with pytest.raises(UnitPlanError, match="outside"):
        parse_unit_plan(valid_plan)


def test_rejects_opening_on_an_unknown_wall(valid_plan: dict[str, Any]) -> None:
    valid_plan["openings"][0]["wall"] = "outline:999"

    with pytest.raises(UnitPlanError, match="unknown wall"):
        parse_unit_plan(valid_plan)


def test_rejects_opening_that_overruns_its_wall(valid_plan: dict[str, Any]) -> None:
    valid_plan["openings"][0]["width_m"] = 500.0

    with pytest.raises(UnitPlanError, match="does not fit"):
        parse_unit_plan(valid_plan)


def test_rejects_opening_starting_before_the_wall(valid_plan: dict[str, Any]) -> None:
    valid_plan["openings"][0]["offset_m"] = -1.0

    with pytest.raises(UnitPlanError, match="does not fit"):
        parse_unit_plan(valid_plan)


def test_rejects_opening_taller_than_the_ceiling(valid_plan: dict[str, Any]) -> None:
    valid_plan["openings"][0]["head_m"] = valid_plan["ceiling_height_m"] + 0.5

    with pytest.raises(UnitPlanError, match="ceiling"):
        parse_unit_plan(valid_plan)


def test_rejects_opening_with_sill_above_head(valid_plan: dict[str, Any]) -> None:
    valid_plan["openings"][0]["sill_m"] = 2.0
    valid_plan["openings"][0]["head_m"] = 1.0

    with pytest.raises(UnitPlanError, match="sill"):
        parse_unit_plan(valid_plan)


def test_walls_expose_outline_edges_and_partitions(valid_plan: dict[str, Any]) -> None:
    """Openings reference walls by id, so the id scheme is part of the contract."""
    plan = parse_unit_plan(valid_plan)
    wall_ids = {wall.id for wall in plan.walls}

    assert f"outline:{len(valid_plan['outline']) - 1}" in wall_ids
    assert len(plan.walls) == len(valid_plan["outline"]) + len(valid_plan["partitions"])
    for opening in plan.openings:
        assert opening.wall in wall_ids


def test_wall_lengths_are_positive(valid_plan: dict[str, Any]) -> None:
    for wall in parse_unit_plan(valid_plan).walls:
        assert wall.length_m > 0
