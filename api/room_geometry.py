"""Pure supported-Room geometry: convex hull minus an L's reflex triangle.

Every subject passed here is convex (Product/access/Zone/walker/swept hull).
A supported L is exactly its convex hull minus the open triangle between the
reflex vertex and its two neighbours. Hull containment plus SAT separation from
that triangle therefore proves containment of the *whole* subject, not samples.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot

Point = tuple[float, float]
Polygon = tuple[Point, ...]


def cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def signed_area(points: Polygon) -> float:
    # Translate before products to avoid cancellation at large world coordinates.
    origin = points[0]
    return sum(cross(origin, points[i], points[i + 1]) for i in range(1, len(points) - 1)) / 2


def reflex_indices(points: Polygon) -> tuple[int, ...]:
    orientation = 1 if signed_area(points) > 0 else -1
    return tuple(i for i in range(len(points)) if cross(points[i - 1], points[i], points[(i + 1) % len(points)]) * orientation < 0)


def supported_l(points: Polygon) -> bool:
    if len(points) != 6 or len(reflex_indices(points)) != 1:
        return False
    for i, point in enumerate(points):
        before, after = points[i - 1], points[(i + 1) % len(points)]
        a, b = (point[0] - before[0], point[1] - before[1]), (after[0] - point[0], after[1] - point[1])
        if abs(a[0] * b[0] + a[1] * b[1]) > 1e-9 * hypot(*a) * hypot(*b):
            return False
    return True


def inward_normal(points: Polygon, start: Point, end: Point) -> Point:
    """Boundary winding, corrected for an independently reversed wall segment."""
    direction = 0
    for i, point in enumerate(points):
        following = points[(i + 1) % len(points)]
        if (point, following) == (start, end):
            direction = 1
            break
        if (point, following) == (end, start):
            direction = -1
            break
    if not direction:
        raise ValueError("Wall does not match the Room boundary")
    dx, dz = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dz)
    sign = direction * (1 if signed_area(points) > 0 else -1)
    normal = (-dz / length * sign, dx / length * sign)
    return tuple(0.0 if value == 0 else value for value in normal)


def convex_hull(points: Polygon) -> Polygon:
    ordered = sorted(set(points))
    lower: list[Point] = []
    upper: list[Point] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


@dataclass(frozen=True)
class RoomGeometry:
    boundary: Polygon
    planes: tuple[tuple[Point, Point], ...]
    notch: Polygon = ()


def prepare_polygon(points: Polygon) -> RoomGeometry:
    reflex = reflex_indices(points)
    hull = convex_hull(points) if reflex else points
    planes = tuple((a, inward_normal(hull, a, hull[(i + 1) % len(hull)])) for i, a in enumerate(hull))
    notch = () if not reflex else (points[reflex[0] - 1], points[reflex[0]], points[(reflex[0] + 1) % len(points)])
    return RoomGeometry(points, planes, notch)


def axes(points: Polygon):
    for i, point in enumerate(points):
        following = points[(i + 1) % len(points)]
        dx, dz = following[0] - point[0], following[1] - point[1]
        length = hypot(dx, dz)
        if length:
            yield (-dz / length, dx / length)


def separation(first: Polygon, second: Polygon) -> float:
    """Largest SAT separating gap; negative means positive interior overlap."""
    best = -float("inf")
    for axis in (*axes(first), *axes(second)):
        a = tuple(p[0] * axis[0] + p[1] * axis[1] for p in first)
        b = tuple(p[0] * axis[0] + p[1] * axis[1] for p in second)
        best = max(best, min(b) - max(a), min(a) - max(b))
    return best


def hull_depth(geometry: RoomGeometry, polygon: Polygon) -> float:
    return min((p[0] - start[0]) * normal[0] + (p[1] - start[1]) * normal[1]
               for p in polygon for start, normal in geometry.planes)


def contains_convex(geometry: RoomGeometry, polygon: Polygon, slack: float) -> bool:
    if hull_depth(geometry, polygon) < -slack:
        return False
    return not geometry.notch or separation(polygon, geometry.notch) >= -slack


def segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dz = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dz)
    # Positive Product dimensions can round to coincident subject vertices.
    # Normalize before projection so nonzero subnormal edges do not underflow
    # when squared; a collapsed edge is exactly its endpoint for distance.
    if length == 0:
        return hypot(point[0] - start[0], point[1] - start[1])
    ux, uz = dx / length, dz / length
    along = max(0.0, min(length, (point[0] - start[0]) * ux + (point[1] - start[1]) * uz))
    return hypot(point[0] - start[0] - along * ux, point[1] - start[1] - along * uz)


def point_depth(geometry: RoomGeometry, point: Point) -> float:
    if not geometry.notch:
        return hull_depth(geometry, (point,))
    boundary = geometry.boundary
    distance = min(segment_distance(point, a, boundary[(i + 1) % len(boundary)]) for i, a in enumerate(boundary))
    inside = False
    x, z = point
    for i, a in enumerate(boundary):
        b = boundary[(i + 1) % len(boundary)]
        if (a[1] > z) != (b[1] > z) and x < (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return distance if inside else -distance


def polygon_clearance(geometry: RoomGeometry, polygon: Polygon) -> float:
    if not geometry.notch:
        return hull_depth(geometry, polygon)
    depth = min(point_depth(geometry, p) for p in polygon)
    gap = separation(polygon, geometry.notch)
    if gap < 0:
        return min(depth, gap)
    # A reflex corner can be nearest to the middle of a subject edge.
    reflex = geometry.notch[1]
    return min(depth, *(segment_distance(reflex, a, polygon[(i + 1) % len(polygon)]) for i, a in enumerate(polygon)))
