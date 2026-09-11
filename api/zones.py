"""Deterministic server-owned Zone derivation for convex Room Shells."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import cos, hypot, pi, sin

from .models import RoomShell, Vec2, WallSegment, Zone, ZoneBounds, ZoneDerivationReport, ZoneOffer

SUBDIVISION_M = 0.25
BOUNDARY_TOLERANCE_M = 0.001
MINIMUM_ZONE_M = 0.60
MAX_INTERVALS_PER_AXIS = 128
MAX_ATOMIC_CELLS = 16_384


class ZoneDerivationError(ValueError):
    code = "ZONE_DERIVATION_UNSUPPORTED"


@dataclass(frozen=True, order=True)
class _Rect:
    min_z: float
    min_x: float
    max_z: float
    max_x: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def depth(self) -> float:
        return self.max_z - self.min_z

    def corners(self) -> tuple[Vec2, Vec2, Vec2, Vec2]:
        return (
            (self.min_x, self.min_z),
            (self.max_x, self.min_z),
            (self.max_x, self.max_z),
            (self.min_x, self.max_z),
        )


def _normalise(vector: Vec2) -> Vec2:
    length = hypot(*vector)
    return (vector[0] / length, vector[1] / length)


def _floor_centre(room: RoomShell) -> Vec2:
    return (
        sum(point[0] for point in room.floorPolygon) / len(room.floorPolygon),
        sum(point[1] for point in room.floorPolygon) / len(room.floorPolygon),
    )


def _wall_basis(room: RoomShell, wall: WallSegment) -> tuple[Vec2, Vec2, Vec2]:
    along = _normalise((wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]))
    candidate = (-along[1], along[0])
    midpoint = ((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2)
    centre = _floor_centre(room)
    towards_centre = (centre[0] - midpoint[0], centre[1] - midpoint[1])
    inward = candidate if candidate[0] * towards_centre[0] + candidate[1] * towards_centre[1] >= 0 else (-candidate[0], -candidate[1])
    return along, inward, midpoint


def _opening_polygons(room: RoomShell) -> tuple[tuple[Vec2, ...], ...]:
    walls = {wall.id: wall for wall in room.walls}
    polygons: list[tuple[Vec2, ...]] = []
    for opening in sorted(room.openings, key=lambda item: item.id):
        wall = walls[opening.wallId]
        along, inward, midpoint = _wall_basis(room, wall)
        wall_centre = (
            midpoint[0] + along[0] * opening.offsetAlongWallM,
            midpoint[1] + along[1] * opening.offsetAlongWallM,
        )
        half_width = opening.widthM / 2
        if opening.clearanceDepthM > BOUNDARY_TOLERANCE_M:
            polygons.append((
                (wall_centre[0] - along[0] * half_width, wall_centre[1] - along[1] * half_width),
                (wall_centre[0] + along[0] * half_width, wall_centre[1] + along[1] * half_width),
                (
                    wall_centre[0] + along[0] * half_width + inward[0] * opening.clearanceDepthM,
                    wall_centre[1] + along[1] * half_width + inward[1] * opening.clearanceDepthM,
                ),
                (
                    wall_centre[0] - along[0] * half_width + inward[0] * opening.clearanceDepthM,
                    wall_centre[1] - along[1] * half_width + inward[1] * opening.clearanceDepthM,
                ),
            ))
        if opening.doorSwing is None:
            continue
        if opening.doorSwing.hingeSide == "start":
            hinge = (
                wall_centre[0] - along[0] * half_width,
                wall_centre[1] - along[1] * half_width,
            )
            closed = along
        else:
            hinge = (
                wall_centre[0] + along[0] * half_width,
                wall_centre[1] + along[1] * half_width,
            )
            closed = (-along[0], -along[1])
        conservative_radius = opening.widthM / cos(pi / 64)
        arc = tuple((
            hinge[0] + conservative_radius * (closed[0] * cos(theta) + inward[0] * sin(theta)),
            hinge[1] + conservative_radius * (closed[1] * cos(theta) + inward[1] * sin(theta)),
        ) for theta in (index * pi / 32 for index in range(17)))
        polygons.append((hinge, *arc))
    return tuple(polygons)


def _polygon_bounds(points: tuple[Vec2, ...], room_bounds: _Rect) -> _Rect | None:
    min_x = max(room_bounds.min_x, min(point[0] for point in points))
    max_x = min(room_bounds.max_x, max(point[0] for point in points))
    min_z = max(room_bounds.min_z, min(point[1] for point in points))
    max_z = min(room_bounds.max_z, max(point[1] for point in points))
    if max_x - min_x <= BOUNDARY_TOLERANCE_M or max_z - min_z <= BOUNDARY_TOLERANCE_M:
        return None
    return _Rect(min_z, min_x, max_z, max_x)


def _point_inside_convex(room: RoomShell, point: Vec2) -> bool:
    signs: list[float] = []
    for index, first in enumerate(room.floorPolygon):
        second = room.floorPolygon[(index + 1) % len(room.floorPolygon)]
        cross = (second[0] - first[0]) * (point[1] - first[1]) - (second[1] - first[1]) * (point[0] - first[0])
        edge_length = hypot(second[0] - first[0], second[1] - first[1])
        signed_distance = cross / edge_length
        if abs(signed_distance) > BOUNDARY_TOLERANCE_M:
            signs.append(signed_distance)
    return not signs or all(value >= 0 for value in signs) or all(value <= 0 for value in signs)


def _rectangles_overlap(first: _Rect, second: _Rect) -> bool:
    return (
        min(first.max_x, second.max_x) - max(first.min_x, second.min_x) > BOUNDARY_TOLERANCE_M
        and min(first.max_z, second.max_z) - max(first.min_z, second.min_z) > BOUNDARY_TOLERANCE_M
    )


def _axis_cuts(low: float, high: float, special: tuple[float, ...]) -> tuple[float, ...]:
    interval_count = int((high - low) / SUBDIVISION_M)
    values = {round(low, 9), round(high, 9), *(round(value, 9) for value in special if low < value < high)}
    for index in range(1, interval_count + 1):
        value = low + index * SUBDIVISION_M
        if value < high:
            values.add(round(value, 9))
    cuts = tuple(sorted(values))
    if len(cuts) - 1 > MAX_INTERVALS_PER_AXIS:
        raise ZoneDerivationError(
            f"Zone subdivision requires {len(cuts) - 1} intervals on one axis; the supported limit is {MAX_INTERVALS_PER_AXIS}"
        )
    return cuts


def _merge_axis(rectangles: tuple[_Rect, ...], horizontal: bool) -> tuple[_Rect, ...]:
    groups: dict[tuple[float, float], list[_Rect]] = {}
    for rectangle in rectangles:
        key = (
            (rectangle.min_z, rectangle.max_z)
            if horizontal
            else (rectangle.min_x, rectangle.max_x)
        )
        groups.setdefault(key, []).append(rectangle)

    merged: list[_Rect] = []
    for key in sorted(groups):
        ordered = sorted(
            groups[key],
            key=(lambda rectangle: (rectangle.min_x, rectangle.max_x))
            if horizontal
            else (lambda rectangle: (rectangle.min_z, rectangle.max_z)),
        )
        current = ordered[0]
        for following in ordered[1:]:
            contiguous = (
                abs(current.max_x - following.min_x) <= 1e-9
                if horizontal
                else abs(current.max_z - following.min_z) <= 1e-9
            )
            if contiguous:
                current = (
                    _Rect(current.min_z, current.min_x, current.max_z, following.max_x)
                    if horizontal
                    else _Rect(current.min_z, current.min_x, following.max_z, current.max_x)
                )
            else:
                merged.append(current)
                current = following
        merged.append(current)
    return tuple(sorted(merged))


def _canonical(value: float) -> str:
    rounded = round(value, 6)
    return "0" if abs(rounded) < 0.0000005 else f"{rounded:.6f}".rstrip("0").rstrip(".")


def derive_zones(room: RoomShell) -> ZoneOffer:
    """Return only bounded, contained rectangles derived from server Room facts."""
    xs = tuple(point[0] for point in room.floorPolygon)
    zs = tuple(point[1] for point in room.floorPolygon)
    room_bounds = _Rect(min(zs), min(xs), max(zs), max(xs))
    exclusions = tuple(
        bound
        for polygon in _opening_polygons(room)
        if (bound := _polygon_bounds(polygon, room_bounds)) is not None
    )
    x_special = tuple(point[0] for point in room.floorPolygon) + tuple(value for rect in exclusions for value in (rect.min_x, rect.max_x))
    z_special = tuple(point[1] for point in room.floorPolygon) + tuple(value for rect in exclusions for value in (rect.min_z, rect.max_z))
    x_cuts = _axis_cuts(room_bounds.min_x, room_bounds.max_x, x_special)
    z_cuts = _axis_cuts(room_bounds.min_z, room_bounds.max_z, z_special)
    raw_cells = (len(x_cuts) - 1) * (len(z_cuts) - 1)
    if raw_cells > MAX_ATOMIC_CELLS:
        raise ZoneDerivationError(
            f"Zone subdivision requires {raw_cells} atomic cells; the supported limit is {MAX_ATOMIC_CELLS}"
        )

    atomic: list[_Rect] = []
    for z_index in range(len(z_cuts) - 1):
        for x_index in range(len(x_cuts) - 1):
            cell = _Rect(z_cuts[z_index], x_cuts[x_index], z_cuts[z_index + 1], x_cuts[x_index + 1])
            if not all(_point_inside_convex(room, corner) for corner in cell.corners()):
                continue
            if any(_rectangles_overlap(cell, exclusion) for exclusion in exclusions):
                continue
            atomic.append(cell)

    merged = tuple(atomic)
    previous_count = -1
    while previous_count != len(merged):
        previous_count = len(merged)
        merged = _merge_axis(_merge_axis(merged, horizontal=True), horizontal=False)
    retained = tuple(
        rectangle
        for rectangle in sorted(merged)
        if rectangle.width + BOUNDARY_TOLERANCE_M >= MINIMUM_ZONE_M
        and rectangle.depth + BOUNDARY_TOLERANCE_M >= MINIMUM_ZONE_M
    )
    zones: list[Zone] = []
    for index, rectangle in enumerate(retained, start=1):
        canonical = ",".join(_canonical(value) for value in (
            rectangle.min_x,
            rectangle.min_z,
            rectangle.max_x,
            rectangle.max_z,
        ))
        digest = sha256(f"{room.id}|{canonical}".encode("utf-8")).hexdigest()[:12]
        zones.append(Zone(
            id=f"zone-{digest}",
            label=f"Placement Zone {index}",
            bounds=ZoneBounds(
                minX=rectangle.min_x,
                minZ=rectangle.min_z,
                maxX=rectangle.max_x,
                maxZ=rectangle.max_z,
            ),
        ))
    return ZoneOffer(
        roomId=room.id,
        zones=tuple(zones),
        derivation=ZoneDerivationReport(
            subdivisionM=SUBDIVISION_M,
            boundaryToleranceM=BOUNDARY_TOLERANCE_M,
            minimumWidthM=MINIMUM_ZONE_M,
            minimumDepthM=MINIMUM_ZONE_M,
            maxIntervalsPerAxis=MAX_INTERVALS_PER_AXIS,
            maxAtomicCells=MAX_ATOMIC_CELLS,
        ),
    )
