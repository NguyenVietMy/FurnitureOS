"""Authoritative deterministic placement and fit validation."""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, sin

from .models import (
    AccessRegion, FitMeasurements, FitResultValue, FitSuccess, Footprint, InvalidFit,
    InvalidFitReason, Placement, Product, ProductFace, RoomShell, Vec2, WallSegment,
)

CANONICAL_FRONT_AXIS = "+z"


@dataclass(frozen=True)
class Tolerances:
    wall_contact_m: float = 0.01
    bounds_slack_m: float = 0.001
    floor_contact_m: float = 0.002


DEFAULT_TOLERANCES = Tolerances()


def rectangular_room_shell(room_id: str, width_m: float, depth_m: float, ceiling_height_m: float) -> RoomShell:
    if not all(isfinite(value) and value > 0 for value in (width_m, depth_m, ceiling_height_m)):
        raise ValueError(f"Room {room_id} must have positive finite width, depth and ceiling height")
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
    return 0.0 if abs(value) < 1e-9 else value


def yaw_to_forward(yaw: float) -> Vec2:
    return (_round_noise(sin(yaw)), _round_noise(cos(yaw)))


def yaw_to_right(yaw: float) -> Vec2:
    return (_round_noise(cos(yaw)), _round_noise(-sin(yaw)))


def _normalise(direction: Vec2) -> Vec2:
    length = hypot(*direction)
    if length == 0:
        raise ValueError("Cannot normalise a zero-length direction")
    return (_round_noise(direction[0] / length), _round_noise(direction[1] / length))


def face_normal(face: ProductFace, yaw: float) -> Vec2:
    forward, right = yaw_to_forward(yaw), yaw_to_right(yaw)
    return {"front": forward, "back": (-forward[0], -forward[1]), "right": right, "left": (-right[0], -right[1])}[face]


def face_half_extent_m(product: Product, face: ProductFace) -> float:
    return product.dimensionsM.depthM / 2 if face in ("front", "back") else product.dimensionsM.widthM / 2


def footprint_of(product: Product, centre: Vec2, yaw: float) -> Footprint:
    right, forward = yaw_to_right(yaw), yaw_to_forward(yaw)
    half_width, half_depth = product.dimensionsM.widthM / 2, product.dimensionsM.depthM / 2
    corners = tuple((
        centre[0] + right[0] * half_width * width_sign + forward[0] * half_depth * depth_sign,
        centre[1] + right[1] * half_width * width_sign + forward[1] * half_depth * depth_sign,
    ) for width_sign, depth_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1)))
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


def signed_distance_to_wall(room: RoomShell, wall: WallSegment, point: Vec2) -> float:
    inward = wall_inward_normal(room, wall)
    return (point[0] - wall.start[0]) * inward[0] + (point[1] - wall.start[1]) * inward[1]


def inside_depth(room: RoomShell, point: Vec2) -> float:
    return min(signed_distance_to_wall(room, wall, point) for wall in room.walls)


def _clearance(room: RoomShell, footprint: Footprint) -> float:
    return min(inside_depth(room, corner) for corner in footprint.corners)


def _measurements(product: Product, placement: Placement, footprint: Footprint, clearance: float, wall_gap: float | None = None) -> FitMeasurements:
    floor_gap = placement.position[1]
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


def validate_placement(product: Product, room: RoomShell, placement: Placement, tolerances: Tolerances = DEFAULT_TOLERANCES) -> FitResultValue:
    if product.id != placement.productId:
        raise ValueError("Placement productId must match Product id")
    centre = (placement.position[0], placement.position[2])
    footprint = footprint_of(product, centre, placement.yaw)
    clearance = _clearance(room, footprint)
    measurements = _measurements(product, placement, footprint, clearance)
    if product.placementClass != "floor-standing":
        return _invalid("placement-class-cannot-stand-on-floor", f"{product.id} is {product.placementClass}; this path only places floor-standing Products", product, room, measurements)
    if abs(placement.position[1]) > tolerances.floor_contact_m:
        return _invalid("not-resting-on-floor", f"{product.id} floor-centre origin is {placement.position[1]:.3f} m from the floor", product, room, measurements)
    if measurements.topM > room.ceilingHeightM + tolerances.bounds_slack_m:
        return _invalid("exceeds-ceiling-height", f"{product.id} placed top is {measurements.topM:.3f} m but the Room ceiling is {room.ceilingHeightM:.3f} m", product, room, measurements)
    if placement.wallContact:
        contact = placement.wallContact
        if contact.face not in product.wallContactFaces:
            return _invalid("wall-contact-face-not-allowed", f"{product.id} may not contact a wall with its {contact.face} face", product, room, measurements)
        wall = get_wall(room, contact.wallId)
        normal = face_normal(contact.face, placement.yaw)
        half_extent = face_half_extent_m(product, contact.face)
        contact_point = (centre[0] + normal[0] * half_extent, centre[1] + normal[1] * half_extent)
        wall_gap = signed_distance_to_wall(room, wall, contact_point)
        measurements = _measurements(product, placement, footprint, clearance, wall_gap)
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
    for region in product.accessRegions:
        if region.required:
            region_clearance = _clearance(room, access_footprint(product, region, centre, placement.yaw))
            if region_clearance < -tolerances.bounds_slack_m:
                return _invalid("access-region-outside-room", f"{product.id} needs {region.depthM:.3f} m of {region.purpose} off its {region.face} face", product, room, measurements)
    return FitSuccess(status="fits", placement=placement, measurements=measurements)


def place_against_wall(product: Product, room: RoomShell, wall_id: str, face: ProductFace = "back", offset_along_wall_m: float = 0, tolerances: Tolerances = DEFAULT_TOLERANCES) -> FitResultValue:
    wall = get_wall(room, wall_id)
    if face not in product.wallContactFaces:
        centre = floor_centre(room)
        placement = Placement(productId=product.id, position=(centre[0], 0, centre[1]), yaw=0, wallContact={"wallId": wall_id, "face": face})
        footprint = footprint_of(product, centre, 0)
        return _invalid("wall-contact-face-not-allowed", f"{product.id} may not contact a wall with its {face} face", product, room, _measurements(product, placement, footprint, _clearance(room, footprint)))
    length = hypot(wall.end[0] - wall.start[0], wall.end[1] - wall.start[1])
    along = ((wall.end[0] - wall.start[0]) / length, (wall.end[1] - wall.start[1]) / length)
    midpoint = ((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2)
    yaw = wall_facing_yaw(room, wall)
    contact_normal = face_normal(face, yaw)
    half_extent = face_half_extent_m(product, face)
    centre = (
        midpoint[0] + along[0] * offset_along_wall_m - contact_normal[0] * half_extent,
        midpoint[1] + along[1] * offset_along_wall_m - contact_normal[1] * half_extent,
    )
    placement = Placement(productId=product.id, position=(centre[0], 0, centre[1]), yaw=yaw, wallContact={"wallId": wall.id, "face": face})
    return validate_placement(product, room, placement, tolerances)
