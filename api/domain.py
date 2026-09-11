"""Authoritative deterministic placement and fit validation."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
from math import atan2, cos, hypot, isfinite, pi, sin
from typing import Iterator

from .catalogue.contract import Catalogue
from .models import (
    AccessRegion, DesignFailure, DesignRequest, DesignResultValue, FitMeasurements,
    FitResultValue, FitSuccess, Footprint, InvalidFit, InvalidFitReason, Placement,
    PlacementIntent, MAX_GEOMETRY_M, Product, ProductFace, RoomShell, SearchReport,
    SolvedDesign, Vec2, WallContact, WallSegment, Zone,
)
from .zones import ZoneDerivationError, derive_zones

CANONICAL_FRONT_AXIS = "+z"


@dataclass(frozen=True)
class Tolerances:
    wall_contact_m: float = 0.01
    bounds_slack_m: float = 0.001
    floor_contact_m: float = 0.002


DEFAULT_TOLERANCES = Tolerances()
SEARCH_STEP_M = 0.1
MAX_SEARCH_CANDIDATES = 256
NUMERIC_NOISE_M = 1e-9


def rectangular_room_shell(room_id: str, width_m: float, depth_m: float, ceiling_height_m: float) -> RoomShell:
    if not all(isfinite(value) and 0 < value <= MAX_GEOMETRY_M for value in (width_m, depth_m, ceiling_height_m)):
        raise ValueError(
            f"Room {room_id} must have positive finite width, depth and ceiling height "
            f"at most {MAX_GEOMETRY_M:g} m"
        )
    half_width, half_depth = width_m / 2, depth_m / 2
    north_west, north_east = (-half_width, -half_depth), (half_width, -half_depth)
    south_east, south_west = (half_width, half_depth), (-half_width, half_depth)
    return RoomShell.model_validate({
        "id": room_id,
        "floorPolygon": [north_west, south_west, south_east, north_east],
        "ceilingHeightM": ceiling_height_m,
        "walls": [
            {"id": "wall-north", "label": "North wall", "start": north_west, "end": north_east},
            {"id": "wall-east", "label": "East wall", "start": north_east, "end": south_east},
            {"id": "wall-south", "label": "South wall", "start": south_east, "end": south_west},
            {"id": "wall-west", "label": "West wall", "start": south_west, "end": north_west},
        ],
    })


def _round_noise(value: float) -> float:
    return 0.0 if abs(value) < NUMERIC_NOISE_M else value


def yaw_to_forward(yaw: float) -> Vec2:
    return (_round_noise(sin(yaw)), _round_noise(cos(yaw)))


def yaw_to_right(yaw: float) -> Vec2:
    return (_round_noise(cos(yaw)), _round_noise(-sin(yaw)))


def _normalise(direction: Vec2) -> Vec2:
    length = hypot(*direction)
    if not isfinite(length) or length == 0:
        raise ValueError("Cannot normalise a zero-length or nonfinite direction")
    return (_round_noise(direction[0] / length), _round_noise(direction[1] / length))


def face_normal(face: ProductFace, yaw: float) -> Vec2:
    forward, right = yaw_to_forward(yaw), yaw_to_right(yaw)
    return {"front": forward, "back": (-forward[0], -forward[1]), "right": right, "left": (-right[0], -right[1])}[face]


def face_half_extent_m(product: Product, face: ProductFace) -> float:
    return product.dimensionsM.depthM / 2 if face in ("front", "back") else product.dimensionsM.widthM / 2


def footprint_of(product: Product, centre: Vec2, yaw: float) -> Footprint:
    if not all(isfinite(value) for value in (*centre, yaw)):
        raise ValueError("Product footprint inputs must be finite")
    right, forward = yaw_to_right(yaw), yaw_to_forward(yaw)
    half_width, half_depth = product.dimensionsM.widthM / 2, product.dimensionsM.depthM / 2
    corners = tuple((
        centre[0] + right[0] * half_width * width_sign + forward[0] * half_depth * depth_sign,
        centre[1] + right[1] * half_width * width_sign + forward[1] * half_depth * depth_sign,
    ) for width_sign, depth_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1)))
    if not all(isfinite(value) for point in corners for value in point):
        raise ValueError("Product footprint produced nonfinite geometry")
    return Footprint(centre=centre, yaw=yaw, widthM=product.dimensionsM.widthM, depthM=product.dimensionsM.depthM, corners=corners)


def access_footprint(product: Product, region: AccessRegion, centre: Vec2, yaw: float) -> Footprint:
    normal = face_normal(region.face, yaw)
    half_extent = face_half_extent_m(product, region.face)
    span = product.dimensionsM.widthM if region.face in ("front", "back") else product.dimensionsM.depthM
    region_centre = (
        centre[0] + normal[0] * (half_extent + region.depthM / 2),
        centre[1] + normal[1] * (half_extent + region.depthM / 2),
    )
    region_yaw = atan2(normal[0], normal[1])
    right, forward = yaw_to_right(region_yaw), yaw_to_forward(region_yaw)
    corners = tuple((
        region_centre[0] + right[0] * width_sign * span / 2 + forward[0] * depth_sign * region.depthM / 2,
        region_centre[1] + right[1] * width_sign * span / 2 + forward[1] * depth_sign * region.depthM / 2,
    ) for width_sign, depth_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1)))
    if not all(isfinite(value) for point in corners for value in point):
        raise ValueError("Product access region produced nonfinite geometry")
    return Footprint(centre=region_centre, yaw=region_yaw, widthM=span, depthM=region.depthM, corners=corners)


def floor_centre(room: RoomShell) -> Vec2:
    return (
        sum(point[0] for point in room.floorPolygon) / len(room.floorPolygon),
        sum(point[1] for point in room.floorPolygon) / len(room.floorPolygon),
    )


def get_wall(room: RoomShell, wall_id: str) -> WallSegment:
    for wall in room.walls:
        if wall.id == wall_id:
            return wall
    raise ValueError(f'Room {room.id} has no wall "{wall_id}"')


def wall_inward_normal(room: RoomShell, wall: WallSegment) -> Vec2:
    along = (wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
    candidate = _normalise((-along[1], along[0]))
    centre = floor_centre(room)
    midpoint = ((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2)
    towards_centre = (centre[0] - midpoint[0], centre[1] - midpoint[1])
    return candidate if candidate[0] * towards_centre[0] + candidate[1] * towards_centre[1] >= 0 else (-candidate[0], -candidate[1])


def wall_facing_yaw(room: RoomShell, wall: WallSegment) -> float:
    inward = wall_inward_normal(room, wall)
    return _round_noise(atan2(inward[0], inward[1]))


def _wall_contact_yaw(room: RoomShell, wall: WallSegment, face: ProductFace) -> float:
    back_yaw = wall_facing_yaw(room, wall)
    adjustment = {"back": 0.0, "front": pi, "right": pi / 2, "left": -pi / 2}[face]
    return _round_noise(back_yaw + adjustment)


def signed_distance_to_wall(room: RoomShell, wall: WallSegment, point: Vec2) -> float:
    inward = wall_inward_normal(room, wall)
    return (point[0] - wall.start[0]) * inward[0] + (point[1] - wall.start[1]) * inward[1]


def inside_depth(room: RoomShell, point: Vec2) -> float:
    return min(signed_distance_to_wall(room, wall, point) for wall in room.walls)


def _clearance(room: RoomShell, footprint: Footprint) -> float:
    return min(inside_depth(room, corner) for corner in footprint.corners)


def _measurements(
    product: Product,
    footprint: Footprint,
    clearance: float,
    floor_gap: float,
    wall_gap: float | None = None,
) -> FitMeasurements:
    return FitMeasurements(
        footprint=footprint, clearanceM=clearance, wallGapM=wall_gap,
        heightM=product.dimensionsM.heightM, floorGapM=floor_gap,
        topM=floor_gap + product.dimensionsM.heightM,
    )


def _invalid(reason: InvalidFitReason, detail: str, product: Product, room: RoomShell, measurements: FitMeasurements) -> InvalidFit:
    return InvalidFit(status="invalid-fit", reason=reason, detail=detail, productId=product.id, roomId=room.id, measurements=measurements)


def _room_span(room: RoomShell) -> tuple[float, float]:
    xs = [point[0] for point in room.floorPolygon]
    zs = [point[1] for point in room.floorPolygon]
    return max(xs) - min(xs), max(zs) - min(zs)


def _product_exceeds_room_span(product: Product, room: RoomShell, tolerances: Tolerances) -> bool:
    room_span = _room_span(room)
    product_span = sorted((product.dimensionsM.widthM, product.dimensionsM.depthM))
    return product_span[0] > min(room_span) + tolerances.bounds_slack_m or product_span[1] > max(room_span) + tolerances.bounds_slack_m


def _axis_projections(points: tuple[Vec2, ...], axis: Vec2) -> tuple[float, float]:
    values = tuple(point[0] * axis[0] + point[1] * axis[1] for point in points)
    return min(values), max(values)


def _polygons_overlap(first: tuple[Vec2, ...], second: tuple[Vec2, ...], slack_m: float) -> bool:
    for polygon in (first, second):
        for index, point in enumerate(polygon):
            following = polygon[(index + 1) % len(polygon)]
            edge = (following[0] - point[0], following[1] - point[1])
            axis = _normalise((-edge[1], edge[0]))
            first_min, first_max = _axis_projections(first, axis)
            second_min, second_max = _axis_projections(second, axis)
            if min(first_max, second_max) - max(first_min, second_min) <= slack_m:
                return False
    return True


def _wall_basis(room: RoomShell, wall: WallSegment) -> tuple[Vec2, Vec2, Vec2]:
    along = _normalise((wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]))
    inward = wall_inward_normal(room, wall)
    midpoint = ((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2)
    return along, inward, midpoint


def _opening_clearance_polygon(room: RoomShell, opening_index: int) -> tuple[Vec2, ...]:
    opening = room.openings[opening_index]
    wall = get_wall(room, opening.wallId)
    along, inward, midpoint = _wall_basis(room, wall)
    wall_centre = (
        midpoint[0] + along[0] * opening.offsetAlongWallM,
        midpoint[1] + along[1] * opening.offsetAlongWallM,
    )
    half_width = opening.widthM / 2
    depth = opening.clearanceDepthM
    return (
        (wall_centre[0] - along[0] * half_width, wall_centre[1] - along[1] * half_width),
        (wall_centre[0] + along[0] * half_width, wall_centre[1] + along[1] * half_width),
        (wall_centre[0] + along[0] * half_width + inward[0] * depth, wall_centre[1] + along[1] * half_width + inward[1] * depth),
        (wall_centre[0] - along[0] * half_width + inward[0] * depth, wall_centre[1] - along[1] * half_width + inward[1] * depth),
    )


def _door_swing_polygon(room: RoomShell, opening_index: int) -> tuple[Vec2, ...]:
    opening = room.openings[opening_index]
    assert opening.doorSwing is not None
    wall = get_wall(room, opening.wallId)
    along, inward, midpoint = _wall_basis(room, wall)
    wall_centre = (
        midpoint[0] + along[0] * opening.offsetAlongWallM,
        midpoint[1] + along[1] * opening.offsetAlongWallM,
    )
    if opening.doorSwing.hingeSide == "start":
        hinge = (
            wall_centre[0] - along[0] * opening.widthM / 2,
            wall_centre[1] - along[1] * opening.widthM / 2,
        )
        closed = along
    else:
        hinge = (
            wall_centre[0] + along[0] * opening.widthM / 2,
            wall_centre[1] + along[1] * opening.widthM / 2,
        )
        closed = (-along[0], -along[1])
    # Circumscribe, rather than inscribe, the true quarter disk. At every
    # segment midpoint the chord is tangent to the real radius, so no sliver of
    # the physical swing can escape validation between samples.
    conservative_radius = opening.widthM / cos(pi / 64)
    arc = tuple((
        hinge[0] + conservative_radius * (closed[0] * cos(theta) + inward[0] * sin(theta)),
        hinge[1] + conservative_radius * (closed[1] * cos(theta) + inward[1] * sin(theta)),
    ) for theta in (index * pi / 32 for index in range(17)))
    return (hinge, *arc)


def _vertical_intervals_overlap(
    first_bottom: float,
    first_top: float,
    second_bottom: float,
    second_top: float,
    slack_m: float,
) -> bool:
    return min(first_top, second_top) - max(first_bottom, second_bottom) > slack_m


def validate_placement(
    product: Product,
    room: RoomShell,
    placement: Placement,
    tolerances: Tolerances = DEFAULT_TOLERANCES,
    occupied: tuple[tuple[Product, Placement], ...] = (),
) -> FitResultValue:
    if product.id != placement.productId:
        raise ValueError("Placement productId must match Product id")
    centre = (placement.position[0], placement.position[2])
    footprint = footprint_of(product, centre, placement.yaw)
    clearance = _clearance(room, footprint)
    measurements = _measurements(product, footprint, clearance, placement.position[1])
    if product.placementClass not in ("floor-standing", "floor-covering"):
        return _invalid(
            "placement-class-cannot-stand-on-floor",
            f"{product.id} is {product.placementClass}; this path only places floor-standing or floor-covering Products",
            product,
            room,
            measurements,
        )
    if abs(placement.position[1]) > tolerances.floor_contact_m:
        return _invalid("not-resting-on-floor", f"{product.id} floor-centre origin is {placement.position[1]:.3f} m from the floor", product, room, measurements)
    if measurements.topM > room.ceilingHeightM + tolerances.bounds_slack_m:
        return _invalid("exceeds-ceiling-height", f"{product.id} placed top is {measurements.topM:.3f} m but the Room ceiling is {room.ceilingHeightM:.3f} m", product, room, measurements)
    for contact_index, contact in enumerate(placement.wallContacts):
        if contact.face not in product.wallContactFaces:
            return _invalid("wall-contact-face-not-allowed", f"{product.id} may not contact a wall with its {contact.face} face", product, room, measurements)
        wall = get_wall(room, contact.wallId)
        normal = face_normal(contact.face, placement.yaw)
        outward = tuple(-value for value in wall_inward_normal(room, wall))
        alignment = normal[0] * outward[0] + normal[1] * outward[1]
        if alignment < 1 - 1e-7:
            return _invalid(
                "wall-contact-not-aligned",
                f"{product.id} {contact.face} face is not aligned with {contact.wallId}",
                product,
                room,
                measurements,
            )
        half_extent = face_half_extent_m(product, contact.face)
        contact_point = (centre[0] + normal[0] * half_extent, centre[1] + normal[1] * half_extent)
        wall_gap = signed_distance_to_wall(room, wall, contact_point)
        if contact_index == 0:
            measurements = _measurements(product, footprint, clearance, placement.position[1], wall_gap)
        if abs(wall_gap) > tolerances.wall_contact_m:
            return _invalid("not-touching-declared-wall", f"{product.id} is not touching {contact.wallId}", product, room, measurements)
        span = product.dimensionsM.widthM if contact.face in ("front", "back") else product.dimensionsM.depthM
        wall_length = hypot(wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
        if span > wall_length + tolerances.bounds_slack_m:
            if clearance < -tolerances.bounds_slack_m and _product_exceeds_room_span(product, room, tolerances):
                return _invalid("product-exceeds-room-bounds", f"{product.id} footprint does not fit inside the Room Shell", product, room, measurements)
            return _invalid("wall-shorter-than-product", f"{product.id} spans {span:.3f} m along {contact.wallId}, which is {wall_length:.3f} m", product, room, measurements)
    if clearance < -tolerances.bounds_slack_m:
        reason: InvalidFitReason = "product-exceeds-room-bounds" if _product_exceeds_room_span(product, room, tolerances) else "footprint-outside-room"
        return _invalid(reason, f"{product.id} footprint does not fit inside the Room Shell", product, room, measurements)
    for opening_index, opening in enumerate(room.openings):
        if opening.kind != "door" and not _vertical_intervals_overlap(
            measurements.floorGapM,
            measurements.topM,
            opening.bottomM,
            opening.bottomM + opening.heightM,
            tolerances.bounds_slack_m,
        ):
            continue
        if opening.clearanceDepthM > tolerances.bounds_slack_m and _polygons_overlap(
            footprint.corners,
            _opening_clearance_polygon(room, opening_index),
            tolerances.bounds_slack_m,
        ):
            return _invalid(
                "opening-exclusion",
                f"{product.id} intersects required clearance for Opening {opening.id}",
                product,
                room,
                measurements,
            )
        if opening.doorSwing is not None and _polygons_overlap(
            footprint.corners,
            _door_swing_polygon(room, opening_index),
            tolerances.bounds_slack_m,
        ):
            return _invalid(
                "door-swing-exclusion",
                f"{product.id} intersects the inward swing of door Opening {opening.id}",
                product,
                room,
                measurements,
            )
    for region in product.accessRegions:
        if region.required:
            region_clearance = _clearance(room, access_footprint(product, region, centre, placement.yaw))
            if region_clearance < -tolerances.bounds_slack_m:
                return _invalid("access-region-outside-room", f"{product.id} needs {region.depthM:.3f} m of {region.purpose} off its {region.face} face", product, room, measurements)
    required_access = tuple(
        access_footprint(product, region, centre, placement.yaw)
        for region in product.accessRegions if region.required
    )
    for opening_index, opening in enumerate(room.openings):
        if opening.kind != "door":
            continue
        door_exclusions: tuple[tuple[Vec2, ...], ...] = (_door_swing_polygon(room, opening_index),)
        if opening.clearanceDepthM > tolerances.bounds_slack_m:
            door_exclusions += (_opening_clearance_polygon(room, opening_index),)
        if any(
            _polygons_overlap(region.corners, exclusion, tolerances.bounds_slack_m)
            for region in required_access
            for exclusion in door_exclusions
        ):
            return _invalid(
                "access-region-blocked",
                f"Required access for {product.id} intersects door Opening {opening.id}",
                product,
                room,
                measurements,
            )
    for other_product, other_placement in occupied:
        other_centre = (other_placement.position[0], other_placement.position[2])
        other_footprint = footprint_of(other_product, other_centre, other_placement.yaw)
        floor_covering_overlap = {
            product.placementClass,
            other_product.placementClass,
        } == {"floor-standing", "floor-covering"}
        current_is_walkable_covering = (
            product.placementClass == "floor-covering"
            and other_product.placementClass == "floor-standing"
        )
        other_is_walkable_covering = (
            other_product.placementClass == "floor-covering"
            and product.placementClass == "floor-standing"
        )
        if (
            not floor_covering_overlap
            and _polygons_overlap(footprint.corners, other_footprint.corners, tolerances.bounds_slack_m)
        ):
            return _invalid(
                "product-collision",
                f"{product.id} overlaps Product {other_product.id}",
                product,
                room,
                measurements,
            )
        other_access = tuple(
            access_footprint(other_product, region, other_centre, other_placement.yaw)
            for region in other_product.accessRegions if region.required
        )
        if (
            not current_is_walkable_covering
            and any(_polygons_overlap(footprint.corners, region.corners, tolerances.bounds_slack_m) for region in other_access)
        ):
            return _invalid(
                "access-region-blocked",
                f"{product.id} blocks required access for Product {other_product.id}",
                product,
                room,
                measurements,
            )
        if (
            not other_is_walkable_covering
            and any(_polygons_overlap(other_footprint.corners, region.corners, tolerances.bounds_slack_m) for region in required_access)
        ):
            return _invalid(
                "access-region-blocked",
                f"Product {other_product.id} blocks required access for {product.id}",
                product,
                room,
                measurements,
            )
    return FitSuccess(status="fits", placement=placement, measurements=measurements)


def place_against_wall(
    product: Product,
    room: RoomShell,
    wall_id: str,
    face: ProductFace = "back",
    offset_along_wall_m: float = 0,
    tolerances: Tolerances = DEFAULT_TOLERANCES,
    occupied: tuple[tuple[Product, Placement], ...] = (),
    instance_id: str | None = None,
    additional_wall_contacts: tuple[WallContact, ...] = (),
) -> FitResultValue:
    if not isfinite(offset_along_wall_m):
        raise ValueError("Wall-relative offset must be finite")
    wall = get_wall(room, wall_id)
    if face not in product.wallContactFaces:
        centre = floor_centre(room)
        placement = Placement(instanceId=instance_id, productId=product.id, position=(centre[0], 0, centre[1]), yaw=0, wallContact={"wallId": wall_id, "face": face})
        footprint = footprint_of(product, centre, 0)
        return _invalid("wall-contact-face-not-allowed", f"{product.id} may not contact a wall with its {face} face", product, room, _measurements(product, footprint, _clearance(room, footprint), placement.position[1]))
    length = hypot(wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
    along = ((wall.end[0] - wall.start[0]) / length, (wall.end[1] - wall.start[1]) / length)
    midpoint = ((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2)
    yaw = _wall_contact_yaw(room, wall, face)
    contact_normal = face_normal(face, yaw)
    half_extent = face_half_extent_m(product, face)
    centre = (
        midpoint[0] + along[0] * offset_along_wall_m - contact_normal[0] * half_extent,
        midpoint[1] + along[1] * offset_along_wall_m - contact_normal[1] * half_extent,
    )
    primary_contact = WallContact(wallId=wall.id, face=face)
    if any(abs(value) > MAX_GEOMETRY_M for value in centre):
        footprint = footprint_of(product, centre, yaw)
        clearance = _clearance(room, footprint)
        contact_point = (
            centre[0] + contact_normal[0] * half_extent,
            centre[1] + contact_normal[1] * half_extent,
        )
        measurements = _measurements(
            product,
            footprint,
            clearance,
            0.0,
            signed_distance_to_wall(room, wall, contact_point),
        )
        reason: InvalidFitReason = (
            "product-exceeds-room-bounds"
            if _product_exceeds_room_span(product, room, tolerances)
            else "footprint-outside-room"
        )
        return _invalid(
            reason,
            f"{product.id} footprint does not fit inside the Room Shell",
            product,
            room,
            measurements,
        )
    placement = Placement(
        instanceId=instance_id,
        productId=product.id,
        position=(centre[0], 0, centre[1]),
        yaw=yaw,
        wallContact=primary_contact,
        wallContacts=(primary_contact, *additional_wall_contacts),
    )
    return validate_placement(product, room, placement, tolerances, occupied)


def _wall_offsets(product: Product, wall: WallSegment, face: ProductFace) -> Iterator[float]:
    """Yield the deterministic lattice lazily; callers own the candidate budget."""
    length = hypot(wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
    span = product.dimensionsM.widthM if face in ("front", "back") else product.dimensionsM.depthM
    if not isfinite(length) or not isfinite(span):
        raise ValueError("Wall candidate geometry must be finite")
    limit = max(0.0, (length - span) / 2)
    yield 0.0
    distance = SEARCH_STEP_M
    while distance < limit - 1e-9:
        yield round(distance, 9)
        yield round(-distance, 9)
        distance += SEARCH_STEP_M
    if limit > 1e-9:
        rounded_limit = round(limit, 9)
        previous = round(distance - SEARCH_STEP_M, 9)
        if rounded_limit != previous:
            yield rounded_limit
            yield -rounded_limit


def _corner_offset(room: RoomShell, primary: WallSegment, adjacent_wall_id: str, span_m: float) -> float | None:
    adjacent = next((wall for wall in room.walls if wall.id == adjacent_wall_id), None)
    if adjacent is None:
        return None
    shared_start = primary.start in (adjacent.start, adjacent.end)
    shared_end = primary.end in (adjacent.start, adjacent.end)
    if shared_start == shared_end:
        return None
    length = hypot(primary.end[0] - primary.start[0], primary.end[1] - primary.start[1])
    edge_offset = max(0.0, (length - span_m) / 2)
    return -edge_offset if shared_start else edge_offset


def _corner_secondary_face(
    room: RoomShell,
    primary: WallSegment,
    adjacent: WallSegment,
    primary_face: ProductFace,
) -> ProductFace | None:
    yaw = _wall_contact_yaw(room, primary, primary_face)
    candidates: tuple[ProductFace, ProductFace] = (
        ("left", "right") if primary_face in ("front", "back") else ("front", "back")
    )
    adjacent_inward = wall_inward_normal(room, adjacent)
    adjacent_outward = (-adjacent_inward[0], -adjacent_inward[1])
    ranked = sorted(
        (
            (face_normal(face, yaw)[0] * adjacent_outward[0] + face_normal(face, yaw)[1] * adjacent_outward[1], face)
            for face in candidates
        ),
        reverse=True,
    )
    alignment, face = ranked[0]
    return face if alignment >= 1 - 1e-7 else None


def _design_failure(
    reason: str,
    detail: str,
    intent_id: str,
    attempted: int,
    limit: int,
    *,
    exhaustive: bool = True,
) -> DesignFailure:
    return DesignFailure.model_validate({
        "status": "failed",
        "reason": reason,
        "detail": detail,
        "failedIntentId": intent_id,
        "search": {
            "attemptedCandidates": attempted,
            "candidateLimit": limit,
            "exhaustive": exhaustive,
        },
    })


@dataclass(frozen=True)
class _PreparedIntent:
    intent: PlacementIntent
    product: Product
    wall: WallSegment | None = None
    fixed_offset: float | None = None
    has_continuous_positions: bool = False
    additional_wall_contacts: tuple[WallContact, ...] = ()
    zone: Zone | None = None

    def offsets(self) -> Iterator[float]:
        if self.wall is None:
            return
        if self.fixed_offset is not None:
            yield self.fixed_offset
        else:
            yield from _wall_offsets(self.product, self.wall, self.intent.face)


_WALL_INTENTS = ("against", "centred_on", "in_corner")
_RELATIVE_INTENTS = ("adjacent_to", "facing", "flanking")
_ZONE_INTENTS = ("in_zone",)


def _opposite_face(face: ProductFace) -> ProductFace:
    return {"front": "back", "back": "front", "left": "right", "right": "left"}[face]


def _actual_wall_contacts(
    product: Product,
    room: RoomShell,
    centre: Vec2,
    yaw: float,
    tolerances: Tolerances = DEFAULT_TOLERANCES,
) -> tuple[WallContact, ...]:
    """Publish every real wall contact made by an object-relative candidate."""
    contacts: list[WallContact] = []
    for wall in sorted(room.walls, key=lambda item: item.id):
        wall_outward = tuple(-value for value in wall_inward_normal(room, wall))
        for face in ("back", "front", "left", "right"):
            normal = face_normal(face, yaw)
            alignment = normal[0] * wall_outward[0] + normal[1] * wall_outward[1]
            if alignment < 1 - 1e-7:
                continue
            half_extent = face_half_extent_m(product, face)
            contact_point = (
                centre[0] + normal[0] * half_extent,
                centre[1] + normal[1] * half_extent,
            )
            if abs(signed_distance_to_wall(room, wall, contact_point)) <= tolerances.wall_contact_m:
                contacts.append(WallContact(wallId=wall.id, face=face))
    return tuple(contacts)


def _place_relative(
    product: Product,
    room: RoomShell,
    intent: PlacementIntent,
    reference_product: Product,
    reference_placement: Placement,
    occupied: tuple[tuple[Product, Placement], ...],
    tolerances: Tolerances = DEFAULT_TOLERANCES,
) -> FitResultValue:
    reference_centre = (reference_placement.position[0], reference_placement.position[2])
    reference_yaw = reference_placement.yaw
    if intent.kind == "facing":
        direction = face_normal("front", reference_yaw)
        distance = (
            reference_product.dimensionsM.depthM / 2
            + product.dimensionsM.depthM / 2
            + intent.gapM
        )
        centre = (
            reference_centre[0] + direction[0] * distance,
            reference_centre[1] + direction[1] * distance,
        )
        yaw = atan2(sin(reference_yaw + pi), cos(reference_yaw + pi))
    else:
        assert intent.side is not None
        direction = face_normal(intent.side, reference_yaw)
        distance = (
            face_half_extent_m(reference_product, intent.side)
            + face_half_extent_m(product, _opposite_face(intent.side))
            + intent.gapM
        )
        if intent.gapM < 0 and distance < 0:
            # Prevalidation admits only sub-slack floating-point noise here.
            distance = 0.0
        centre = (
            reference_centre[0] + direction[0] * distance,
            reference_centre[1] + direction[1] * distance,
        )
        yaw = reference_yaw
        if intent.kind == "flanking":
            forward = face_normal("front", reference_yaw)
            rear_alignment = (
                -reference_product.dimensionsM.depthM / 2
                + product.dimensionsM.depthM / 2
            )
            centre = (
                centre[0] + forward[0] * rear_alignment,
                centre[1] + forward[1] * rear_alignment,
            )

    footprint = footprint_of(product, centre, yaw)
    clearance = _clearance(room, footprint)
    if any(abs(value) > MAX_GEOMETRY_M for value in centre):
        reason: InvalidFitReason = (
            "product-exceeds-room-bounds"
            if _product_exceeds_room_span(product, room, tolerances)
            else "footprint-outside-room"
        )
        return _invalid(
            reason,
            f"{product.id} object-relative footprint does not fit inside the Room Shell",
            product,
            room,
            _measurements(product, footprint, clearance, 0.0),
        )
    contacts = _actual_wall_contacts(product, room, centre, yaw, tolerances)
    placement = Placement(
        instanceId=intent.id,
        productId=product.id,
        position=(centre[0], 0, centre[1]),
        yaw=yaw,
        wallContact=contacts[0] if contacts else None,
        wallContacts=contacts,
    )
    return validate_placement(product, room, placement, tolerances, occupied)


def _fit_failure_reason(reason: InvalidFitReason) -> str:
    return {
        "exceeds-ceiling-height": "product-exceeds-ceiling-height",
        "product-collision": "product-collision",
        "access-region-blocked": "access-region-blocked",
        "opening-exclusion": "opening-exclusion",
        "door-swing-exclusion": "door-swing-exclusion",
    }.get(reason, "intent-unsatisfiable")


def _zone_axis_centres(low: float, high: float) -> tuple[float, ...]:
    if high < low - DEFAULT_TOLERANCES.bounds_slack_m:
        return ()
    if high - low <= DEFAULT_TOLERANCES.bounds_slack_m:
        return ((low + high) / 2,)
    values = {round(low, 9), round(high, 9), round((low + high) / 2, 9)}
    value = low
    while value < high:
        values.add(round(value, 9))
        value += SEARCH_STEP_M
    midpoint = (low + high) / 2
    return tuple(sorted(values, key=lambda item: (abs(item - midpoint), item)))


def _zone_candidates(product: Product, zone: Zone) -> Iterator[tuple[Vec2, float]]:
    bounds = zone.bounds
    for yaw in (0.0, pi / 2, pi, -pi / 2):
        rotated = abs(sin(yaw)) > 0.5
        span_x = product.dimensionsM.depthM if rotated else product.dimensionsM.widthM
        span_z = product.dimensionsM.widthM if rotated else product.dimensionsM.depthM
        xs = _zone_axis_centres(bounds.minX + span_x / 2, bounds.maxX - span_x / 2)
        zs = _zone_axis_centres(bounds.minZ + span_z / 2, bounds.maxZ - span_z / 2)
        # xs and zs are already centre-out. Enumerate their rank grid in
        # expanding squares so the global candidate cap can stop this lazily.
        for rank in range(max(len(xs), len(zs))):
            if rank < len(xs):
                for z_index in range(min(rank + 1, len(zs))):
                    yield (xs[rank], zs[z_index]), yaw
            if rank < len(zs):
                for x_index in range(min(rank, len(xs))):
                    yield (xs[x_index], zs[rank]), yaw


def _place_in_zone(
    product: Product,
    room: RoomShell,
    intent: PlacementIntent,
    zone: Zone,
    centre: Vec2,
    yaw: float,
    occupied: tuple[tuple[Product, Placement], ...],
    tolerances: Tolerances = DEFAULT_TOLERANCES,
) -> FitResultValue:
    footprint = footprint_of(product, centre, yaw)
    bounds = zone.bounds
    inside_zone = all(
        bounds.minX - tolerances.bounds_slack_m <= x <= bounds.maxX + tolerances.bounds_slack_m
        and bounds.minZ - tolerances.bounds_slack_m <= z <= bounds.maxZ + tolerances.bounds_slack_m
        for x, z in footprint.corners
    )
    if not inside_zone:
        return _invalid(
            "footprint-outside-room",
            f'{product.id} footprint does not fit inside offered Zone "{zone.id}"',
            product,
            room,
            _measurements(product, footprint, _clearance(room, footprint), 0.0),
        )
    contacts = _actual_wall_contacts(product, room, centre, yaw, tolerances)
    placement = Placement(
        instanceId=intent.id,
        productId=product.id,
        position=(centre[0], 0, centre[1]),
        yaw=yaw,
        wallContact=contacts[0] if contacts else None,
        wallContacts=contacts,
    )
    return validate_placement(product, room, placement, tolerances, occupied)


def resolve_design(source: Catalogue, request: DesignRequest) -> DesignResultValue:
    """Resolve coordinate-free Placement Intents with bounded deterministic backtracking."""
    if request.maxCandidates > MAX_SEARCH_CANDIDATES:
        raise ValueError(f"Search cannot exceed {MAX_SEARCH_CANDIDATES} candidates")
    intent_ids = [intent.id for intent in request.intents]
    duplicate_intent = next((value for value in intent_ids if intent_ids.count(value) > 1), None)
    if duplicate_intent:
        return _design_failure(
            "duplicate-intent-reference",
            f'Placement Intent id "{duplicate_intent}" is duplicated',
            duplicate_intent,
            0,
            request.maxCandidates,
        )

    intents_by_id = {intent.id: intent for intent in request.intents}
    zone_offer = None
    if any(intent.kind in _ZONE_INTENTS for intent in request.intents):
        try:
            zone_offer = derive_zones(request.room)
        except ZoneDerivationError as error:
            zoned_intent = min(
                (intent for intent in request.intents if intent.kind in _ZONE_INTENTS),
                key=lambda item: item.id,
            )
            return _design_failure(
                "zone-derivation-unsupported",
                str(error),
                zoned_intent.id,
                0,
                request.maxCandidates,
                exhaustive=False,
            )
    zones_by_id = {zone.id: zone for zone in zone_offer.zones} if zone_offer is not None else {}
    products_by_intent: dict[str, Product] = {}
    walls_by_intent: dict[str, WallSegment] = {}
    for intent in sorted(request.intents, key=lambda item: item.id):
        product = source.get(intent.productId)
        if product is None:
            return _design_failure(
                "unknown-product-reference",
                f'Catalogue has no Product "{intent.productId}"',
                intent.id,
                0,
                request.maxCandidates,
            )
        products_by_intent[intent.id] = product
        if intent.kind not in (*_WALL_INTENTS, *_RELATIVE_INTENTS, *_ZONE_INTENTS):
            return _design_failure(
                "unsupported-intent",
                f'Placement Intent kind "{intent.kind}" is not supported',
                intent.id,
                0,
                request.maxCandidates,
            )
        if intent.kind in _WALL_INTENTS:
            if intent.referenceId is not None or intent.side is not None or intent.gapM != 0 or intent.zoneId is not None:
                return _design_failure(
                    "unsupported-intent",
                    f"{intent.kind} accepts wall-relative fields only",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.wallId is None:
                return _design_failure(
                    "unknown-wall-reference",
                    f"{intent.kind} requires wallId",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            wall = next((candidate for candidate in request.room.walls if candidate.id == intent.wallId), None)
            if wall is None:
                return _design_failure(
                    "unknown-wall-reference",
                    f'Room {request.room.id} has no wall "{intent.wallId}"',
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            walls_by_intent[intent.id] = wall
            if intent.face not in product.wallContactFaces:
                return _design_failure(
                    "product-face-not-supported",
                    f"{product.id} may not contact a wall with its {intent.face} face",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.kind == "in_corner" and intent.adjacentWallId is None:
                return _design_failure(
                    "nonadjacent-corner-walls",
                    "in_corner requires adjacentWallId",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.kind != "in_corner" and intent.adjacentWallId is not None:
                return _design_failure(
                    "unsupported-intent",
                    f'{intent.kind} does not accept adjacentWallId',
                    intent.id,
                    0,
                    request.maxCandidates,
                )
        elif intent.kind in _RELATIVE_INTENTS:
            if intent.wallId is not None or intent.adjacentWallId is not None or intent.face != "back" or intent.zoneId is not None:
                return _design_failure(
                    "unsupported-intent",
                    f"{intent.kind} accepts object-relative fields only",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.referenceId is None:
                return _design_failure(
                    "unknown-intent-reference",
                    f"{intent.kind} requires referenceId",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.kind == "adjacent_to" and intent.side is None:
                return _design_failure(
                    "unsupported-intent",
                    "adjacent_to requires side",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.kind == "facing" and intent.side is not None:
                return _design_failure(
                    "unsupported-intent",
                    "facing always uses the referenced Product front and does not accept side",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.kind == "flanking" and intent.side not in ("left", "right"):
                return _design_failure(
                    "invalid-flanking-group",
                    "flanking requires an explicit left or right side",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
        else:
            if (
                intent.wallId is not None
                or intent.adjacentWallId is not None
                or intent.referenceId is not None
                or intent.side is not None
                or intent.face != "back"
                or intent.gapM != 0
            ):
                return _design_failure(
                    "unsupported-intent",
                    "in_zone accepts a server-offered zoneId and neutral defaults only",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if intent.zoneId is None or intent.zoneId not in zones_by_id:
                return _design_failure(
                    "unknown-zone-reference",
                    f'Room {request.room.id} offered no Zone "{intent.zoneId or ""}"',
                    intent.id,
                    0,
                    request.maxCandidates,
                )

    for intent in sorted(request.intents, key=lambda item: item.id):
        if intent.kind not in _RELATIVE_INTENTS:
            continue
        assert intent.referenceId is not None
        if intent.referenceId not in intents_by_id:
            return _design_failure(
                "unknown-intent-reference",
                f'Placement Intent "{intent.id}" references unknown request "{intent.referenceId}"',
                intent.id,
                0,
                request.maxCandidates,
            )
        if intent.referenceId == intent.id:
            return _design_failure(
                "self-intent-reference",
                f'Placement Intent "{intent.id}" cannot reference itself',
                intent.id,
                0,
                request.maxCandidates,
            )
        if intent.gapM < 0:
            reference_product = products_by_intent[intent.referenceId]
            allowed_classes = {
                products_by_intent[intent.id].placementClass,
                reference_product.placementClass,
            }
            if intent.kind != "adjacent_to" or allowed_classes != {"floor-standing", "floor-covering"}:
                return _design_failure(
                    "invalid-relative-gap",
                    "A negative gap is limited to intentional adjacent floor-covering/floor-standing overlap",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            assert intent.side is not None
            centre_separation = (
                face_half_extent_m(reference_product, intent.side)
                + face_half_extent_m(products_by_intent[intent.id], _opposite_face(intent.side))
                + intent.gapM
            )
            if centre_separation < -NUMERIC_NOISE_M:
                return _design_failure(
                    "invalid-relative-gap",
                    "The negative gap reverses the requested side instead of creating intentional overlap",
                    intent.id,
                    0,
                    request.maxCandidates,
                )

    flanking_groups: dict[str, list[PlacementIntent]] = {}
    for intent in request.intents:
        if intent.kind == "flanking":
            assert intent.referenceId is not None
            flanking_groups.setdefault(intent.referenceId, []).append(intent)
    for reference_id, members in sorted(flanking_groups.items()):
        sides = {member.side for member in members}
        gaps = {member.gapM for member in members}
        if len(members) != 2 or sides != {"left", "right"} or len(gaps) != 1:
            failed_id = min((member.id for member in members), default=reference_id)
            return _design_failure(
                "invalid-flanking-group",
                f'Flanking reference "{reference_id}" requires exactly one left and one right request with a shared gapM',
                failed_id,
                0,
                request.maxCandidates,
            )

    children: dict[str, list[str]] = {intent_id: [] for intent_id in intents_by_id}
    indegree = {intent_id: 0 for intent_id in intents_by_id}
    for intent in request.intents:
        if intent.kind in _RELATIVE_INTENTS:
            assert intent.referenceId is not None
            children[intent.referenceId].append(intent.id)
            indegree[intent.id] += 1
    ready = [intent_id for intent_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    topological_ids: list[str] = []
    while ready:
        intent_id = heapq.heappop(ready)
        topological_ids.append(intent_id)
        for child_id in sorted(children[intent_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                heapq.heappush(ready, child_id)
    if len(topological_ids) != len(request.intents):
        cyclic_id = min(intent_id for intent_id, degree in indegree.items() if degree > 0)
        return _design_failure(
            "cyclic-intent-reference",
            f'Placement Intent reference graph contains a cycle involving "{cyclic_id}"',
            cyclic_id,
            0,
            request.maxCandidates,
        )

    prepared: list[_PreparedIntent] = []
    for intent_id in topological_ids:
        intent = intents_by_id[intent_id]
        product = products_by_intent[intent_id]
        if intent.kind in _RELATIVE_INTENTS:
            prepared.append(_PreparedIntent(intent=intent, product=product))
            continue
        if intent.kind in _ZONE_INTENTS:
            assert intent.zoneId is not None
            zone = zones_by_id[intent.zoneId]
            bounds = zone.bounds
            has_continuous_positions = any(
                (
                    bounds.maxX - bounds.minX > span_x + DEFAULT_TOLERANCES.bounds_slack_m
                    or bounds.maxZ - bounds.minZ > span_z + DEFAULT_TOLERANCES.bounds_slack_m
                )
                for span_x, span_z in (
                    (product.dimensionsM.widthM, product.dimensionsM.depthM),
                    (product.dimensionsM.depthM, product.dimensionsM.widthM),
                )
            )
            prepared.append(_PreparedIntent(
                intent=intent,
                product=product,
                zone=zone,
                has_continuous_positions=has_continuous_positions,
            ))
            continue
        wall = walls_by_intent[intent_id]
        if intent.kind == "in_corner":
            assert intent.adjacentWallId is not None
            adjacent = next((candidate for candidate in request.room.walls if candidate.id == intent.adjacentWallId), None)
            if adjacent is None:
                return _design_failure(
                    "unknown-wall-reference",
                    f'Room {request.room.id} has no wall "{intent.adjacentWallId}"',
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            span = product.dimensionsM.widthM if intent.face in ("front", "back") else product.dimensionsM.depthM
            offset = _corner_offset(request.room, wall, adjacent.id, span)
            if offset is None:
                return _design_failure(
                    "nonadjacent-corner-walls",
                    f'Walls "{wall.id}" and "{adjacent.id}" do not share exactly one corner',
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            secondary_face = _corner_secondary_face(request.room, wall, adjacent, intent.face)
            if secondary_face is None:
                return _design_failure(
                    "corner-angle-not-supported",
                    f'Walls "{wall.id}" and "{adjacent.id}" do not form a right angle supported by rectangular Product faces',
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            if secondary_face not in product.wallContactFaces:
                return _design_failure(
                    "product-face-not-supported",
                    f"{product.id} may not contact {adjacent.id} with its {secondary_face} face",
                    intent.id,
                    0,
                    request.maxCandidates,
                )
            prepared.append(_PreparedIntent(
                intent=intent,
                product=product,
                wall=wall,
                fixed_offset=offset,
                additional_wall_contacts=(WallContact(wallId=adjacent.id, face=secondary_face),),
            ))
        elif intent.kind == "centred_on":
            prepared.append(_PreparedIntent(intent=intent, product=product, wall=wall, fixed_offset=0.0))
        else:
            wall_length = hypot(wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
            product_span = product.dimensionsM.widthM if intent.face in ("front", "back") else product.dimensionsM.depthM
            prepared.append(_PreparedIntent(
                intent=intent,
                product=product,
                wall=wall,
                has_continuous_positions=wall_length > product_span + DEFAULT_TOLERANCES.bounds_slack_m,
            ))

    attempted = 0
    budget_intent_id: str | None = None
    last_invalid: tuple[PlacementIntent, InvalidFit] | None = None

    def search(
        index: int,
        placements: dict[str, Placement],
        fits: dict[str, FitSuccess],
    ) -> tuple[dict[str, Placement], dict[str, FitSuccess]] | None:
        nonlocal attempted, budget_intent_id, last_invalid
        if index == len(prepared):
            return placements, fits
        current = prepared[index]
        candidates: Iterator[tuple[str, object | None]]
        if current.intent.kind in _RELATIVE_INTENTS:
            candidates = iter((("relative", None),))
        elif current.intent.kind in _ZONE_INTENTS:
            assert current.zone is not None
            candidates = (("zone", candidate) for candidate in _zone_candidates(current.product, current.zone))
        else:
            candidates = (("wall", offset) for offset in current.offsets())
        for candidate_kind, candidate in candidates:
            if attempted >= request.maxCandidates:
                budget_intent_id = current.intent.id
                return None
            occupied = tuple(
                (products_by_intent[instance_id], placement)
                for instance_id, placement in placements.items()
            )
            if candidate_kind == "relative":
                assert current.intent.referenceId is not None
                reference_id = current.intent.referenceId
                fit = _place_relative(
                    current.product,
                    request.room,
                    current.intent,
                    products_by_intent[reference_id],
                    placements[reference_id],
                    occupied,
                )
            elif candidate_kind == "zone":
                assert current.zone is not None and candidate is not None
                centre, yaw = candidate
                fit = _place_in_zone(
                    current.product,
                    request.room,
                    current.intent,
                    current.zone,
                    centre,
                    yaw,
                    occupied,
                )
            else:
                assert current.wall is not None and candidate is not None
                fit = place_against_wall(
                    current.product,
                    request.room,
                    current.wall.id,
                    current.intent.face,
                    candidate,
                    occupied=occupied,
                    instance_id=current.intent.id,
                    additional_wall_contacts=current.additional_wall_contacts,
                )
            attempted += 1
            if fit.status != "fits":
                last_invalid = (current.intent, fit)
                continue
            solution = search(
                index + 1,
                {**placements, current.intent.id: fit.placement},
                {**fits, current.intent.id: fit},
            )
            if solution is not None:
                return solution
            if budget_intent_id is not None:
                return None
        return None

    solution = search(0, {}, {})
    if solution is None:
        if budget_intent_id is not None:
            return _design_failure(
                "search-exhausted",
                f"Search stopped at the declared {request.maxCandidates}-candidate limit before all supported assignments were checked",
                budget_intent_id,
                attempted,
                request.maxCandidates,
                exhaustive=False,
            )
        if any(item.has_continuous_positions for item in prepared):
            failed_id = last_invalid[0].id if last_invalid else request.intents[-1].id
            return _design_failure(
                "search-exhausted",
                f"The deterministic {SEARCH_STEP_M:.1f} m wall grid has no valid complete assignment; continuous positions were not proven impossible",
                failed_id,
                attempted,
                request.maxCandidates,
                exhaustive=False,
            )
        if last_invalid is None:
            return _design_failure(
                "intent-unsatisfiable",
                "No supported complete assignment could be constructed",
                request.intents[-1].id,
                attempted,
                request.maxCandidates,
            )
        failed_intent, invalid = last_invalid
        return _design_failure(
            _fit_failure_reason(invalid.reason),
            invalid.detail,
            failed_intent.id,
            attempted,
            request.maxCandidates,
        )

    placements_by_id, fits_by_id = solution
    return SolvedDesign(
        status="solved",
        room=request.room,
        intents=request.intents,
        products=tuple(products_by_intent[intent.id] for intent in request.intents),
        placements=tuple(placements_by_id[intent.id] for intent in request.intents),
        fits=tuple(fits_by_id[intent.id] for intent in request.intents),
        search=SearchReport(
            attemptedCandidates=attempted,
            candidateLimit=request.maxCandidates,
            exhaustive=True,
        ),
        zones=zone_offer.zones if zone_offer is not None else (),
    )
