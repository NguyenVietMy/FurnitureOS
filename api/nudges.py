"""Sound, conservative translation certificates for interactive Nudge previews."""
from __future__ import annotations

from bisect import insort
from collections import deque
from dataclasses import dataclass
from math import hypot, isfinite
import time
from typing import Callable, Iterable

from .circulation import (
    CIRCULATION_TOLERANCE_M,
    CirculationWitness,
    _collisions,
    _inside_prepared_room,
    _swept_polygon,
    _walker_polygon,
    validate_circulation_with_witness,
)
from .domain import (
    DEFAULT_TOLERANCES,
    _axis_projections,
    _door_swing_polygon,
    _normalise,
    _opening_clearance_polygon,
    _vertical_intervals_overlap,
    access_footprint,
    face_half_extent_m,
    face_normal,
    footprint_of,
    get_wall,
    signed_distance_to_wall,
    wall_inward_normal,
)
from .models import (
    NudgeHalfPlane,
    NudgeRegionAvailable,
    Placement,
    Product,
    SolvedDesign,
    Vec2,
    WallContact,
)

MAX_DISPLACEMENT_M = 1.0
CERTIFICATE_INWARD_MARGIN_M = 1e-7
SERVER_MEMBERSHIP_MARGIN_M = 1e-9
CLIENT_MEMBERSHIP_MARGIN_M = 1e-8
MIN_USEFUL_TRANSLATION_M = 0.05
MAX_HALF_PLANES = 4096
MAX_WITNESS_POLYGONS = 256
MAX_ATTACHMENT_CANDIDATES = 32
REGION_DEADLINE_SECONDS = 2.0
MAX_PLACEMENTS = 20
MAX_ROOM_WALLS = 64
MAX_ROOM_VERTICES = 64
MAX_OPENINGS = 128


@dataclass(frozen=True)
class HalfPlane:
    normal: Vec2
    maximum: float
    reason: str


@dataclass(frozen=True)
class NudgeCertificate:
    region_id: str
    session_id: str
    version: int
    instance_id: str
    origin: Vec2
    fixed_y: float
    fixed_yaw: float
    half_planes: tuple[HalfPlane, ...]
    polygon: tuple[Vec2, ...]
    expires_at: float


class NudgeProofError(RuntimeError):
    pass


@dataclass(frozen=True)
class _SafeBackbone:
    parents: dict[tuple[int, int], tuple[int, int] | None]
    fixed_connectors: tuple[tuple[Vec2, Vec2], ...]


def _dot(first: Vec2, second: Vec2) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _axes(*polygons: tuple[Vec2, ...]) -> tuple[Vec2, ...]:
    values: dict[tuple[int, int], Vec2] = {}
    for polygon in polygons:
        for index, point in enumerate(polygon):
            following = polygon[(index + 1) % len(polygon)]
            edge = (following[0] - point[0], following[1] - point[1])
            if abs(edge[0]) < 1e-15 and abs(edge[1]) < 1e-15:
                continue
            axis = _normalise((-edge[1], edge[0]))
            if axis[0] < -1e-12 or (abs(axis[0]) <= 1e-12 and axis[1] < 0):
                axis = (-axis[0], -axis[1])
            key = (round(axis[0] * 1_000_000_000), round(axis[1] * 1_000_000_000))
            values[key] = axis
    return tuple(values[key] for key in sorted(values))


def _best_separator(
    moving: tuple[Vec2, ...],
    fixed: tuple[Vec2, ...],
    slack_m: float,
    reason: str,
) -> HalfPlane:
    candidates: list[HalfPlane] = []
    for axis in _axes(moving, fixed):
        moving_min, moving_max = _axis_projections(moving, axis)
        fixed_min, fixed_max = _axis_projections(fixed, axis)
        first_maximum = fixed_min - moving_max + slack_m - CERTIFICATE_INWARD_MARGIN_M
        if first_maximum > CLIENT_MEMBERSHIP_MARGIN_M:
            candidates.append(HalfPlane(axis, first_maximum, reason))
        second_maximum = moving_min - fixed_max + slack_m - CERTIFICATE_INWARD_MARGIN_M
        if second_maximum > CLIENT_MEMBERSHIP_MARGIN_M:
            candidates.append(HalfPlane((-axis[0], -axis[1]), second_maximum, reason))
    if not candidates:
        raise NudgeProofError(f"No stable separating axis for {reason}.")
    return max(candidates, key=lambda value: (value.maximum, value.normal[0], value.normal[1]))


def _common_endpoint_separator(
    moving_endpoint: tuple[Vec2, ...],
    fixed_endpoint: tuple[Vec2, ...],
    obstacle: tuple[Vec2, ...],
    slack_m: float,
    reason: str,
) -> HalfPlane:
    candidates: list[HalfPlane] = []
    # Walker squares stay axis-aligned. Their x/z axes and the fixed obstacle
    # axes remain SAT axes of every future tether hull. A baseline diagonal
    # hull edge could disappear, so it cannot certify the owning slack rule.
    for axis in _axes(moving_endpoint, fixed_endpoint, obstacle):
        moving_min, moving_max = _axis_projections(moving_endpoint, axis)
        fixed_min, fixed_max = _axis_projections(fixed_endpoint, axis)
        obstacle_min, obstacle_max = _axis_projections(obstacle, axis)
        if fixed_max <= obstacle_min + slack_m:
            maximum = obstacle_min - moving_max + slack_m - CERTIFICATE_INWARD_MARGIN_M
            if maximum > CLIENT_MEMBERSHIP_MARGIN_M:
                candidates.append(HalfPlane(axis, maximum, reason))
        if fixed_min >= obstacle_max - slack_m:
            maximum = moving_min - obstacle_max + slack_m - CERTIFICATE_INWARD_MARGIN_M
            if maximum > CLIENT_MEMBERSHIP_MARGIN_M:
                candidates.append(HalfPlane((-axis[0], -axis[1]), maximum, reason))
    if not candidates:
        raise NudgeProofError(f"No common endpoint separator for {reason}.")
    return max(candidates, key=lambda value: (value.maximum, value.normal[0], value.normal[1]))


def _room_half_planes(
    polygon: tuple[Vec2, ...],
    witness: CirculationWitness,
    slack_m: float,
    reason: str,
) -> tuple[HalfPlane, ...]:
    values = []
    for start, inward in witness.room_geometry:
        baseline = min((point[0] - start[0]) * inward[0] + (point[1] - start[1]) * inward[1] for point in polygon)
        maximum = baseline + slack_m - CERTIFICATE_INWARD_MARGIN_M
        if maximum <= CLIENT_MEMBERSHIP_MARGIN_M:
            raise NudgeProofError(f"The current pose has no numeric margin for {reason}.")
        values.append(HalfPlane((-inward[0], -inward[1]), maximum, reason))
    return tuple(values)


def _clip_polygon(polygon: tuple[Vec2, ...], plane: HalfPlane) -> tuple[Vec2, ...]:
    if not polygon:
        return ()
    maximum = plane.maximum - CLIENT_MEMBERSHIP_MARGIN_M
    output: list[Vec2] = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        current_value = _dot(plane.normal, current) - maximum
        previous_value = _dot(plane.normal, previous) - maximum
        current_inside = current_value <= 0
        previous_inside = previous_value <= 0
        if current_inside != previous_inside:
            denominator = previous_value - current_value
            if denominator == 0:
                raise NudgeProofError("Certificate clipping became numerically unstable.")
            ratio = previous_value / denominator
            output.append((
                previous[0] + (current[0] - previous[0]) * ratio,
                previous[1] + (current[1] - previous[1]) * ratio,
            ))
        if current_inside:
            output.append(current)
    deduplicated: list[Vec2] = []
    for point in output:
        if not deduplicated or hypot(point[0] - deduplicated[-1][0], point[1] - deduplicated[-1][1]) > 1e-12:
            deduplicated.append(point)
    if len(deduplicated) > 1 and hypot(
        deduplicated[0][0] - deduplicated[-1][0],
        deduplicated[0][1] - deduplicated[-1][1],
    ) <= 1e-12:
        deduplicated.pop()
    return tuple(deduplicated)


def _deduplicate_half_planes(constraints: Iterable[HalfPlane]) -> tuple[HalfPlane, ...]:
    """Parallel planes have the same normal; only their tightest bound matters."""
    tightest: dict[Vec2, HalfPlane] = {}
    for constraint in constraints:
        # Only identical IEEE-754 normals are interchangeable.
        key = constraint.normal
        previous = tightest.get(key)
        if previous is None or constraint.maximum < previous.maximum:
            tightest[key] = constraint
    return tuple(tightest[key] for key in sorted(tightest))


def _polygon_area(polygon: tuple[Vec2, ...]) -> float:
    return abs(sum(
        point[0] * polygon[(index + 1) % len(polygon)][1]
        - polygon[(index + 1) % len(polygon)][0] * point[1]
        for index, point in enumerate(polygon)
    )) / 2


def _path_to_root(
    key: tuple[int, int],
    parents: dict[tuple[int, int], tuple[int, int] | None],
) -> tuple[tuple[int, int], ...]:
    path = [key]
    seen = {key}
    while parents.get(path[-1]) is not None:
        parent = parents[path[-1]]
        assert parent is not None
        if parent in seen:
            raise NudgeProofError("Circulation witness parent cycle detected.")
        seen.add(parent)
        path.append(parent)
    return tuple(path)


def _choose_attachment(
    access_target: Vec2,
    access_face_normal: Vec2,
    selected_footprint: tuple[Vec2, ...],
    witness: CirculationWitness,
    allowed_keys: frozenset[tuple[int, int]],
    selected_instance_id: str,
    deadline: float,
) -> tuple[tuple[int, int], Vec2, tuple[HalfPlane, ...]]:
    selected_min, selected_max = _axis_projections(selected_footprint, access_face_normal)
    del selected_min
    ranked: list[tuple[float, float, tuple[int, int], Vec2]] = []
    for key, point in witness.grid:
        if key not in allowed_keys:
            continue
        if time.monotonic() > deadline:
            raise NudgeProofError("Nudge region certification timed out.")
        square = _walker_polygon(point, witness.clearance_width_m)
        square_min, _square_max = _axis_projections(square, access_face_normal)
        headroom = square_min - selected_max + CIRCULATION_TOLERANCE_M
        if headroom >= MIN_USEFUL_TRANSLATION_M + CERTIFICATE_INWARD_MARGIN_M:
            # Prefer a useful but bounded amount of extra headroom, then the
            # shortest tether. This avoids both the nearest barely-safe node
            # and a needlessly long connector across the Room.
            candidate = (
                -min(headroom, 0.25),
                hypot(point[0] - access_target[0], point[1] - access_target[1]),
                key,
                point,
            )
            if len(ranked) == MAX_ATTACHMENT_CANDIDATES:
                if candidate >= ranked[-1]:
                    continue
                # Eject before inserting: even transiently retain at most 32.
                ranked.pop()
            insort(ranked, candidate)
    for _negative_headroom, _distance, key, point in ranked:
        square = _walker_polygon(point, witness.clearance_width_m)
        connector = _swept_polygon(access_target, point, witness.clearance_width_m)
        if not _inside_prepared_room(witness.room_geometry, connector) or _collisions(connector, witness.obstacles):
            continue
        body_maximum = _axis_projections(selected_footprint, access_face_normal)[1]
        q_minimum = _axis_projections(square, access_face_normal)[0]
        self_maximum = q_minimum - body_maximum + CIRCULATION_TOLERANCE_M - CERTIFICATE_INWARD_MARGIN_M
        if self_maximum <= MIN_USEFUL_TRANSLATION_M:
            continue
        constraints = [HalfPlane(access_face_normal, self_maximum, "selected access tether versus moved Product")]
        moving_square = _walker_polygon(access_target, witness.clearance_width_m)
        if _axis_projections(moving_square, access_face_normal)[0] < body_maximum - CIRCULATION_TOLERANCE_M:
            continue
        try:
            constraints.extend(_room_half_planes(
                moving_square,
                witness,
                CIRCULATION_TOLERANCE_M,
                "selected access tether Room containment",
            ))
            for obstacle_id, obstacle in witness.obstacles:
                if obstacle_id == selected_instance_id:
                    continue
                constraints.append(_common_endpoint_separator(
                    moving_square,
                    square,
                    obstacle,
                    CIRCULATION_TOLERANCE_M,
                    f"selected access tether versus {obstacle_id}",
                ))
        except NudgeProofError:
            continue
        return key, point, tuple(constraints)
    raise NudgeProofError("No farther safe circulation attachment leaves useful movement.")


def _safe_backbone(
    witness: CirculationWitness,
    selected_instance_id: str,
    selected_footprint: tuple[Vec2, ...],
    deadline: float,
    needs_paths: bool,
) -> _SafeBackbone:
    """Choose one connected witness tree that stays usefully clear of the mover."""
    grid = dict(witness.grid)
    fixed_accesses = tuple(
        access for access in witness.accesses
        if not (access.owner_type == "product" and access.owner_id == selected_instance_id)
    )
    if not fixed_accesses:
        raise NudgeProofError("No fixed circulation terminal can anchor the moved Product access.")

    def separator_for(start: Vec2, end: Vec2, reason: str) -> HalfPlane | None:
        corridor = _swept_polygon(start, end, witness.clearance_width_m)
        if not _inside_prepared_room(witness.room_geometry, corridor) or _collisions(corridor, witness.obstacles):
            return None
        try:
            plane = _best_separator(
                selected_footprint,
                corridor,
                CIRCULATION_TOLERANCE_M,
                reason,
            )
        except NudgeProofError:
            return None
        return plane if plane.maximum >= MIN_USEFUL_TRANSLATION_M + CERTIFICATE_INWARD_MARGIN_M else None

    root_access = fixed_accesses[0]
    root_options: list[tuple[float, float, tuple[int, int]]] = []
    for key in root_access.connectors:
        if key not in grid:
            continue
        plane = separator_for(root_access.target, grid[key], f"fixed access {root_access.id}")
        if plane is not None:
            root_options.append((
                -plane.maximum,
                hypot(grid[key][0] - root_access.target[0], grid[key][1] - root_access.target[1]),
                key,
            ))
    if not root_options:
        raise NudgeProofError(f"Fixed access {root_access.id} cannot anchor a useful Nudge witness.")
    root_key = min(root_options)[2]
    if not needs_paths:
        return _SafeBackbone(parents={root_key: None}, fixed_connectors=((root_access.target, grid[root_key]),))

    parents: dict[tuple[int, int], tuple[int, int] | None] = {root_key: None}
    queue: deque[tuple[int, int]] = deque((root_key,))
    while queue:
        if time.monotonic() > deadline:
            raise NudgeProofError("Nudge region certification timed out.")
        current = queue.popleft()
        for delta_x, delta_z in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbour = (current[0] + delta_x, current[1] + delta_z)
            if neighbour in parents or neighbour not in grid:
                continue
            if separator_for(grid[current], grid[neighbour], "preserved circulation witness") is None:
                continue
            parents[neighbour] = current
            queue.append(neighbour)

    fixed_connectors: list[tuple[Vec2, Vec2]] = []
    for access in fixed_accesses:
        options: list[tuple[float, float, tuple[int, int]]] = []
        for key in access.connectors:
            if key not in parents:
                continue
            plane = separator_for(access.target, grid[key], f"fixed access {access.id}")
            if plane is not None:
                options.append((
                    -plane.maximum,
                    hypot(grid[key][0] - access.target[0], grid[key][1] - access.target[1]),
                    key,
                ))
        if not options:
            raise NudgeProofError(f"Fixed access {access.id} has no useful safe witness connector.")
        connector = min(options)[2]
        fixed_connectors.append((access.target, grid[connector]))

    return _SafeBackbone(parents=parents, fixed_connectors=tuple(fixed_connectors))


def _fixed_witness_polygons(
    witness: CirculationWitness,
    parents: dict[tuple[int, int], tuple[int, int] | None],
    fixed_connectors: tuple[tuple[Vec2, Vec2], ...],
    attachments: tuple[tuple[int, int], ...],
    deadline: float,
) -> tuple[tuple[Vec2, ...], ...]:
    grid = dict(witness.grid)
    used_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    point_keys = {point: key for key, point in witness.grid}
    connector_keys = tuple(point_keys[endpoint] for _start, endpoint in fixed_connectors)
    for key in (*attachments, *connector_keys):
        if time.monotonic() > deadline:
            raise NudgeProofError("Nudge region certification timed out.")
        path = _path_to_root(key, parents)
        for first, second in zip(path, path[1:]):
            used_edges.add(tuple(sorted((first, second))))
            if len(used_edges) + len(fixed_connectors) > MAX_WITNESS_POLYGONS:
                raise NudgeProofError(f"The retained circulation witness exceeds {MAX_WITNESS_POLYGONS} polygons.")

    polygons = [
        _swept_polygon(grid[first], grid[second], witness.clearance_width_m)
        for first, second in sorted(used_edges)
    ]
    polygons.extend(
        _swept_polygon(start, end, witness.clearance_width_m)
        for start, end in fixed_connectors
    )
    if len(polygons) > MAX_WITNESS_POLYGONS:
        raise NudgeProofError(
            f"The retained circulation witness needs {len(polygons)} polygons; limit is {MAX_WITNESS_POLYGONS}."
        )
    return tuple(polygons)


def _selected_index(design: SolvedDesign, instance_id: str) -> int:
    for index, placement in enumerate(design.placements):
        if placement.instanceId == instance_id:
            return index
    raise NudgeProofError(f'No Placement instance has id "{instance_id}".')


def build_nudge_certificate(
    design: SolvedDesign,
    instance_id: str,
    clearance_width_m: float,
    *,
    region_id: str,
    session_id: str,
    version: int,
    expires_at: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[NudgeCertificate, NudgeRegionAvailable]:
    started_at = time.monotonic()
    deadline = started_at + REGION_DEADLINE_SECONDS
    if len(design.placements) > MAX_PLACEMENTS:
        raise NudgeProofError(f"Nudge supports at most {MAX_PLACEMENTS} Placements.")
    if len(design.room.walls) > MAX_ROOM_WALLS or len(design.room.floorPolygon) > MAX_ROOM_VERTICES:
        raise NudgeProofError(
            f"Nudge supports at most {MAX_ROOM_WALLS} Room walls and {MAX_ROOM_VERTICES} floor vertices."
        )
    if len(design.room.openings) > MAX_OPENINGS:
        raise NudgeProofError(f"Nudge supports at most {MAX_OPENINGS} Openings.")
    index = _selected_index(design, instance_id)
    product = design.products[index]
    placement = design.placements[index]
    selected_access_count = sum(region.required for region in product.accessRegions)
    all_access_count = sum(region.required for other in design.products for region in other.accessRegions)
    # Bound before allocating footprint/constraint lists. This is an upper
    # bound, deliberately counting optional vertical/exemption branches too.
    constraint_budget = (
        4 + len(design.room.walls) * (1 + selected_access_count)
        + len(design.room.openings) * (2 + 2 * selected_access_count)
        + len(design.products) * (1 + selected_access_count) + all_access_count
        + MAX_WITNESS_POLYGONS
        + selected_access_count * (1 + len(design.room.walls) + len(design.products))
    )
    if constraint_budget > MAX_HALF_PLANES:
        raise NudgeProofError(f"Nudge proof exceeds the {MAX_HALF_PLANES} half-plane preallocation budget.")
    if product.placementClass not in ("floor-standing", "floor-covering"):
        raise NudgeProofError(f"{product.displayName} cannot be translated on the floor.")
    origin = (placement.position[0], placement.position[2])
    selected_footprint = footprint_of(product, origin, placement.yaw).corners
    circulation, witness = validate_circulation_with_witness(design, clearance_width_m)
    if circulation.status != "clear" or witness is None:
        raise NudgeProofError("The current Design has no reusable clear circulation witness.")

    constraints: list[HalfPlane] = [
        HalfPlane((1.0, 0.0), MAX_DISPLACEMENT_M - CERTIFICATE_INWARD_MARGIN_M, "bounded translation"),
        HalfPlane((-1.0, 0.0), MAX_DISPLACEMENT_M - CERTIFICATE_INWARD_MARGIN_M, "bounded translation"),
        HalfPlane((0.0, 1.0), MAX_DISPLACEMENT_M - CERTIFICATE_INWARD_MARGIN_M, "bounded translation"),
        HalfPlane((0.0, -1.0), MAX_DISPLACEMENT_M - CERTIFICATE_INWARD_MARGIN_M, "bounded translation"),
    ]
    constraints.extend(_room_half_planes(
        selected_footprint,
        witness,
        DEFAULT_TOLERANCES.bounds_slack_m,
        "Product Room containment",
    ))

    required_access = tuple(
        (region, access_footprint(product, region, origin, placement.yaw).corners)
        for region in product.accessRegions if region.required
    )
    for _region, polygon in required_access:
        constraints.extend(_room_half_planes(
            polygon,
            witness,
            DEFAULT_TOLERANCES.bounds_slack_m,
            "required access Room containment",
        ))

    top_m = placement.position[1] + product.dimensionsM.heightM
    for opening_index, opening in enumerate(design.room.openings):
        if time.monotonic() > deadline:
            raise NudgeProofError("Nudge region certification timed out.")
        if opening.kind == "door" or _vertical_intervals_overlap(
            placement.position[1],
            top_m,
            opening.bottomM,
            opening.bottomM + opening.heightM,
            DEFAULT_TOLERANCES.bounds_slack_m,
        ):
            if opening.clearanceDepthM > DEFAULT_TOLERANCES.bounds_slack_m:
                constraints.append(_best_separator(
                    selected_footprint,
                    _opening_clearance_polygon(design.room, opening_index),
                    DEFAULT_TOLERANCES.bounds_slack_m,
                    f"Opening {opening.id} clearance",
                ))
            if opening.doorSwing is not None:
                constraints.append(_best_separator(
                    selected_footprint,
                    _door_swing_polygon(design.room, opening_index),
                    DEFAULT_TOLERANCES.bounds_slack_m,
                    f"door {opening.id} swing",
                ))
        if opening.kind == "door":
            exclusions = [_door_swing_polygon(design.room, opening_index)] if opening.doorSwing is not None else []
            if opening.clearanceDepthM > DEFAULT_TOLERANCES.bounds_slack_m:
                exclusions.append(_opening_clearance_polygon(design.room, opening_index))
            for _region, polygon in required_access:
                for exclusion in exclusions:
                    constraints.append(_best_separator(
                        polygon,
                        exclusion,
                        DEFAULT_TOLERANCES.bounds_slack_m,
                        f"required access versus door {opening.id}",
                    ))

    for other_index, (other_product, other_placement) in enumerate(zip(design.products, design.placements, strict=True)):
        if time.monotonic() > deadline:
            raise NudgeProofError("Nudge region certification timed out.")
        if other_index == index:
            continue
        other_centre = (other_placement.position[0], other_placement.position[2])
        other_footprint = footprint_of(other_product, other_centre, other_placement.yaw).corners
        floor_covering_overlap = {product.placementClass, other_product.placementClass} == {"floor-standing", "floor-covering"}
        if not floor_covering_overlap:
            constraints.append(_best_separator(
                selected_footprint,
                other_footprint,
                DEFAULT_TOLERANCES.bounds_slack_m,
                f"Product {other_placement.instanceId or other_product.id}",
            ))
        if not (product.placementClass == "floor-covering" and other_product.placementClass == "floor-standing"):
            for region in other_product.accessRegions:
                if region.required:
                    constraints.append(_best_separator(
                        selected_footprint,
                        access_footprint(other_product, region, other_centre, other_placement.yaw).corners,
                        DEFAULT_TOLERANCES.bounds_slack_m,
                        f"required access for {other_placement.instanceId or other_product.id}",
                    ))
        other_is_walkable_covering = (
            other_product.placementClass == "floor-covering"
            and product.placementClass == "floor-standing"
        )
        if not other_is_walkable_covering:
            for _region, polygon in required_access:
                constraints.append(_best_separator(
                    polygon,
                    other_footprint,
                    DEFAULT_TOLERANCES.bounds_slack_m,
                    f"selected required access versus {other_placement.instanceId or other_product.id}",
                ))

    selected_witness_access = tuple(
        value for value in witness.accesses
        if value.owner_type == "product" and value.owner_id == instance_id
    )
    fixed_witness_access = tuple(
        value for value in witness.accesses
        if not (value.owner_type == "product" and value.owner_id == instance_id)
    )
    attachments: list[tuple[int, int]] = []
    if len(witness.accesses) == 1 and selected_witness_access:
        # A lone access needs no connected tree, but its clearance-width
        # target square still belongs to the complete circulation predicate.
        target_square = _walker_polygon(selected_witness_access[0].target, clearance_width_m)
        constraints.extend(_room_half_planes(target_square, witness, CIRCULATION_TOLERANCE_M, "selected circulation target"))
        for obstacle_id, obstacle in witness.obstacles:
            if obstacle_id != instance_id:
                constraints.append(_best_separator(target_square, obstacle, CIRCULATION_TOLERANCE_M,
                    f"selected circulation target versus {obstacle_id}"))
    backbone: _SafeBackbone | None = None
    if product.placementClass != "floor-covering" and fixed_witness_access:
        backbone = _safe_backbone(
            witness,
            instance_id,
            selected_footprint,
            deadline,
            needs_paths=bool(selected_witness_access) or len(fixed_witness_access) > 1,
        )
    elif product.placementClass == "floor-covering":
        backbone = _SafeBackbone(parents=dict(witness.parents), fixed_connectors=())

    if selected_witness_access and len(witness.accesses) > 1:
        if backbone is None:
            raise NudgeProofError("No fixed circulation terminal can anchor the moved Product access.")
        region_by_index = [region for region in product.accessRegions if region.required]
        if len(selected_witness_access) != len(region_by_index):
            raise NudgeProofError("Selected Product access does not align with the circulation witness.")
        for access, region in zip(selected_witness_access, region_by_index, strict=True):
            if time.monotonic() > deadline:
                raise NudgeProofError("Nudge region certification timed out.")
            attachment_key, _attachment_point, tether_constraints = _choose_attachment(
                access.target,
                face_normal(region.face, placement.yaw),
                selected_footprint,
                witness,
                frozenset(backbone.parents),
                instance_id,
                deadline,
            )
            attachments.append(attachment_key)
            constraints.extend(tether_constraints)

    witness_polygon_count = 0
    if product.placementClass != "floor-covering" and backbone is not None:
        witness_polygons = _fixed_witness_polygons(
            witness,
            backbone.parents,
            backbone.fixed_connectors,
            tuple(attachments),
            deadline,
        )
        witness_polygon_count = len(witness_polygons)
        for polygon in witness_polygons:
            constraints.append(_best_separator(
                selected_footprint,
                polygon,
                CIRCULATION_TOLERANCE_M,
                "preserved circulation witness",
            ))

    constraints = list(_deduplicate_half_planes(constraints))
    if len(constraints) > MAX_HALF_PLANES:
        raise NudgeProofError(f"Nudge proof needs {len(constraints)} constraints; limit is {MAX_HALF_PLANES}.")
    if time.monotonic() > deadline:
        raise NudgeProofError("Nudge region certification timed out.")
    polygon: tuple[Vec2, ...] = (
        (-MAX_DISPLACEMENT_M, -MAX_DISPLACEMENT_M),
        (MAX_DISPLACEMENT_M, -MAX_DISPLACEMENT_M),
        (MAX_DISPLACEMENT_M, MAX_DISPLACEMENT_M),
        (-MAX_DISPLACEMENT_M, MAX_DISPLACEMENT_M),
    )
    for constraint in constraints:
        if time.monotonic() > deadline:
            raise NudgeProofError("Nudge region certification timed out.")
        polygon = _clip_polygon(polygon, constraint)
        if len(polygon) < 3:
            raise NudgeProofError("The conservative Nudge region is empty.")
    if any(not all(isfinite(value) for value in point) for point in polygon):
        raise NudgeProofError("The conservative Nudge region is nonfinite.")
    if any(_dot(constraint.normal, (0.0, 0.0)) > constraint.maximum - CLIENT_MEMBERSHIP_MARGIN_M for constraint in constraints):
        raise NudgeProofError("The authoritative pose is not inside the conservative Nudge region.")
    if _polygon_area(polygon) <= 1e-6 or max(hypot(*point) for point in polygon) < MIN_USEFUL_TRANSLATION_M:
        raise NudgeProofError("The conservative Nudge region has no useful two-dimensional movement.")
    for point in polygon:
        if any(_dot(constraint.normal, point) > constraint.maximum - CLIENT_MEMBERSHIP_MARGIN_M + 1e-12 for constraint in constraints):
            raise NudgeProofError("A serialized Nudge polygon vertex escaped its certificate.")

    certificate = NudgeCertificate(
        region_id=region_id,
        session_id=session_id,
        version=version,
        instance_id=instance_id,
        origin=origin,
        fixed_y=placement.position[1],
        fixed_yaw=placement.yaw,
        half_planes=tuple(constraints),
        polygon=polygon,
        expires_at=expires_at,
    )
    response = NudgeRegionAvailable(
        status="available",
        regionId=region_id,
        sessionId=session_id,
        version=version,
        instanceId=instance_id,
        origin=origin,
        fixedY=placement.position[1],
        fixedYaw=placement.yaw,
        constraints=tuple(NudgeHalfPlane(normal=value.normal, maxDisplacementM=value.maximum) for value in constraints),
        polygon=polygon,
        expiresInMs=max(1, min(120_000, round((expires_at - clock()) * 1000))),
        conservative=True,
        constraintCount=len(constraints),
        witnessPolygonCount=witness_polygon_count,
        attachmentCount=len(attachments),
        computationMs=(time.monotonic() - started_at) * 1000,
        detail="This server-certified convex region is safe but may omit other valid positions.",
    )
    return certificate, response


def certificate_contains(certificate: NudgeCertificate, target: Vec2) -> bool:
    displacement = (target[0] - certificate.origin[0], target[1] - certificate.origin[1])
    return all(
        _dot(plane.normal, displacement) <= plane.maximum - SERVER_MEMBERSHIP_MARGIN_M
        for plane in certificate.half_planes
    )


def nudged_placement(
    product: Product,
    room,
    placement: Placement,
    target: Vec2,
) -> Placement:
    """Translate at fixed y/yaw and retain only wall contacts still physically true."""
    centre = target
    retained: list[WallContact] = []
    for contact in placement.wallContacts:
        wall = get_wall(room, contact.wallId)
        normal = face_normal(contact.face, placement.yaw)
        outward = tuple(-value for value in wall_inward_normal(room, wall))
        if normal[0] * outward[0] + normal[1] * outward[1] < 1 - 1e-7:
            continue
        half_extent = face_half_extent_m(product, contact.face)
        contact_point = (centre[0] + normal[0] * half_extent, centre[1] + normal[1] * half_extent)
        if abs(signed_distance_to_wall(room, wall, contact_point)) <= DEFAULT_TOLERANCES.wall_contact_m:
            retained.append(contact)
    primary = retained[0] if retained else None
    return placement.model_copy(update={
        "position": (target[0], placement.position[1], target[1]),
        "wallContact": primary,
        "wallContacts": tuple(retained),
    }, deep=True)
