"""The unit plan: an apartment's geometry, parsed and validated.

This module owns the contract that every downstream slice reads — the buyer's room
shell, room attribution for totals, and eventually the floorplan tracer's output. Its
public surface is deliberately small:

    load_seed_unit(slug) -> UnitPlan
    parse_unit_plan(raw) -> UnitPlan          (raises UnitPlanError)

Everything else — shoelace area, point-in-polygon, wall derivation, opening
validation — is an implementation detail and must stay one.

Coordinates are metres in a right-handed XY plane, Y forward. The renderer maps this
to three.js XZ; that mapping is the scene layer's business, not this module's.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Point = tuple[float, float]

SEEDS_DIR = Path(__file__).resolve().parent / "seeds"

# Rooms are validated against the outline with a small tolerance: traced coordinates
# carry rounding error, and a vertex a millimetre outside its own wall is not a bug
# worth failing a whole unit over.
CONTAINMENT_TOLERANCE_M = 1e-6


class UnitPlanError(ValueError):
    """A unit plan is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Wall:
    """A wall segment. `id` is the stable reference openings are hung from."""

    id: str
    start: Point
    end: Point
    thickness_m: float

    @property
    def length_m(self) -> float:
        return math.dist(self.start, self.end)


@dataclass(frozen=True)
class Opening:
    """A door or window cut into a wall, positioned along it from the wall's start."""

    wall: str
    kind: Literal["door", "window"]
    offset_m: float
    width_m: float
    sill_m: float
    head_m: float


@dataclass(frozen=True)
class Room:
    key: str
    name: str
    type: str
    polygon: list[Point]


@dataclass(frozen=True)
class UnitPlan:
    slug: str
    name: str
    building: str
    ceiling_height_m: float
    outline: list[Point]
    walls: list[Wall]
    rooms: list[Room]
    openings: list[Opening]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def area_m2(self) -> float:
        return _polygon_area(self.outline)

    @property
    def bedrooms(self) -> int:
        return sum(1 for room in self.rooms if room.type == "bedroom")


def load_seed_unit(slug: str) -> UnitPlan:
    """Load and validate a seeded unit by slug."""
    path = SEEDS_DIR / f"{slug}.json"
    if not path.is_file():
        raise UnitPlanError(f"no seed unit named {slug!r}")
    return parse_unit_plan(json.loads(path.read_text(encoding="utf-8")))


def parse_unit_plan(raw: dict[str, Any]) -> UnitPlan:
    """Parse a raw unit plan, raising UnitPlanError on any inconsistency."""
    outline = _parse_outline(raw.get("outline"))
    ceiling_height_m = _parse_ceiling_height(raw.get("ceiling_height_m"))
    walls = _derive_walls(outline, raw.get("partitions") or [])
    rooms = _parse_rooms(raw.get("rooms") or [], outline)
    openings = _parse_openings(raw.get("openings") or [], walls, ceiling_height_m)

    return UnitPlan(
        slug=str(raw.get("slug") or ""),
        name=str(raw.get("name") or ""),
        building=str(raw.get("building") or ""),
        ceiling_height_m=ceiling_height_m,
        outline=outline,
        walls=walls,
        rooms=rooms,
        openings=openings,
        raw=raw,
    )


# --- parsing helpers -------------------------------------------------------------


def _parse_outline(value: Any) -> list[Point]:
    if not isinstance(value, list) or len(value) < 3:
        raise UnitPlanError("outline must have at least 3 points")
    return [_parse_point(point, "outline") for point in value]


def _parse_point(value: Any, context: str) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise UnitPlanError(f"{context} point must be a pair of numbers, got {value!r}")
    x, y = value
    return (float(x), float(y))


def _parse_ceiling_height(value: Any) -> float:
    try:
        height = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitPlanError("ceiling height must be a number") from exc
    if height <= 0:
        raise UnitPlanError("ceiling height must be positive")
    return height


def _derive_walls(outline: list[Point], partitions: list[Any]) -> list[Wall]:
    """Outline edges first, then interior partitions. Ids follow that order."""
    walls: list[Wall] = [
        Wall(
            id=f"outline:{index}",
            start=start,
            end=outline[(index + 1) % len(outline)],
            thickness_m=0.2,
        )
        for index, start in enumerate(outline)
    ]

    for index, partition in enumerate(partitions):
        walls.append(
            Wall(
                id=f"partition:{index}",
                start=_parse_point(partition.get("start"), "partition"),
                end=_parse_point(partition.get("end"), "partition"),
                thickness_m=float(partition.get("thickness_m", 0.1)),
            )
        )

    for wall in walls:
        if wall.length_m <= 0:
            raise UnitPlanError(f"wall {wall.id} has zero length")

    return walls


def _parse_rooms(raw_rooms: list[Any], outline: list[Point]) -> list[Room]:
    rooms: list[Room] = []
    seen: set[str] = set()

    for raw_room in raw_rooms:
        key = str(raw_room.get("key") or "")
        if key in seen:
            raise UnitPlanError(f"duplicate room key {key!r}")
        seen.add(key)

        polygon = [_parse_point(point, f"room {key}") for point in raw_room.get("polygon") or []]
        if len(polygon) < 3:
            raise UnitPlanError(f"room {key!r} polygon must have at least 3 points")

        for point in polygon:
            if not _point_in_polygon(point, outline):
                raise UnitPlanError(f"room {key!r} has a vertex outside the unit outline: {point}")

        rooms.append(
            Room(
                key=key,
                name=str(raw_room.get("name") or key),
                type=str(raw_room.get("type") or ""),
                polygon=polygon,
            )
        )

    return rooms


def _parse_openings(
    raw_openings: list[Any], walls: list[Wall], ceiling_height_m: float
) -> list[Opening]:
    walls_by_id = {wall.id: wall for wall in walls}
    openings: list[Opening] = []

    for raw_opening in raw_openings:
        wall_id = str(raw_opening.get("wall") or "")
        wall = walls_by_id.get(wall_id)
        if wall is None:
            raise UnitPlanError(f"opening references unknown wall {wall_id!r}")

        offset_m = float(raw_opening.get("offset_m", 0.0))
        width_m = float(raw_opening.get("width_m", 0.0))
        sill_m = float(raw_opening.get("sill_m", 0.0))
        head_m = float(raw_opening.get("head_m", 0.0))

        if width_m <= 0 or offset_m < 0 or offset_m + width_m > wall.length_m:
            raise UnitPlanError(
                f"opening does not fit on wall {wall_id!r}: "
                f"{offset_m}m + {width_m}m exceeds {wall.length_m:.3f}m"
            )
        if sill_m >= head_m:
            raise UnitPlanError(f"opening sill {sill_m}m is not below its head {head_m}m")
        if head_m > ceiling_height_m:
            raise UnitPlanError(
                f"opening head {head_m}m is above the ceiling at {ceiling_height_m}m"
            )

        kind = raw_opening.get("kind")
        if kind not in ("door", "window"):
            raise UnitPlanError(f"opening kind must be 'door' or 'window', got {kind!r}")

        openings.append(
            Opening(
                wall=wall_id,
                kind=kind,
                offset_m=offset_m,
                width_m=width_m,
                sill_m=sill_m,
                head_m=head_m,
            )
        )

    return openings


# --- geometry --------------------------------------------------------------------


def _polygon_area(polygon: list[Point]) -> float:
    """Shoelace area. Absolute, so winding order does not matter."""
    total = 0.0
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Ray casting, treating points on the boundary as inside.

    Room polygons share edges with the outline by construction, so boundary points
    must count as contained or every room would be rejected.
    """
    if _point_on_boundary(point, polygon):
        return True

    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if crossing_x > x:
                inside = not inside
    return inside


def _point_on_boundary(point: Point, polygon: list[Point]) -> bool:
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _distance_to_segment(point, start, end) <= CONTAINMENT_TOLERANCE_M:
            return True
    return False


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.dist(point, (ax + t * dx, ay + t * dy))
