"""Conservative whole-Design walking validation behind one public interface."""
from __future__ import annotations

from collections import deque
from math import floor, hypot

from .domain import (
    _clearance,
    _polygons_overlap,
    _wall_basis,
    access_footprint,
    face_half_extent_m,
    face_normal,
    footprint_of,
)
from .models import (
    CirculationBlocked,
    CirculationClear,
    CirculationRegion,
    CirculationResultValue,
    CirculationUnsupported,
    Footprint,
    SolvedDesign,
    Vec2,
)

GRID_RESOLUTION_M = 0.05
CIRCULATION_TOLERANCE_M = 1e-9
MAX_RAW_LATTICE_POINTS = 50_000
MAX_LATTICE_POINTS_PER_AXIS = 1_000


def _walker_polygon(centre: Vec2, width_m: float) -> tuple[Vec2, Vec2, Vec2, Vec2]:
    half = width_m / 2
    return (
        (centre[0] - half, centre[1] - half),
        (centre[0] + half, centre[1] - half),
        (centre[0] + half, centre[1] + half),
        (centre[0] - half, centre[1] + half),
    )


def _convex_hull(points: tuple[Vec2, ...]) -> tuple[Vec2, ...]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return tuple(unique)

    def cross(origin: Vec2, first: Vec2, second: Vec2) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (first[1] - origin[1]) * (second[0] - origin[0])

    lower: list[Vec2] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Vec2] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def _swept_polygon(start: Vec2, end: Vec2, width_m: float) -> tuple[Vec2, ...]:
    return _convex_hull((*_walker_polygon(start, width_m), *_walker_polygon(end, width_m)))


def _polygon_footprint(points: tuple[Vec2, ...]) -> Footprint:
    xs = [point[0] for point in points]
    zs = [point[1] for point in points]
    return Footprint(
        centre=((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2),
        yaw=0,
        widthM=max(xs) - min(xs),
        depthM=max(zs) - min(zs),
        corners=(points[0], points[1], points[2], points[3]),
    )


def _inside_room(design: SolvedDesign, polygon: tuple[Vec2, ...]) -> bool:
    # The Room is convex, so containing every swept-polygon vertex contains the
    # complete swept polygon. _clearance only reads Footprint.corners.
    if len(polygon) == 4:
        footprint = _polygon_footprint(polygon)
        return _clearance(design.room, footprint) >= -CIRCULATION_TOLERANCE_M
    return all(
        min(
            (point[0] - wall.start[0]) * inward[0] + (point[1] - wall.start[1]) * inward[1]
            for wall in design.room.walls
            for _along, inward, _midpoint in (_wall_basis(design.room, wall),)
        ) >= -CIRCULATION_TOLERANCE_M
        for point in polygon
    )


def _collisions(
    polygon: tuple[Vec2, ...],
    obstacles: tuple[tuple[str, tuple[Vec2, ...]], ...],
) -> tuple[str, ...]:
    return tuple(sorted({
        request_id
        for request_id, obstacle in obstacles
        if _polygons_overlap(polygon, obstacle, CIRCULATION_TOLERANCE_M)
    }))


def _door_region(design: SolvedDesign, opening_index: int, clearance_width_m: float) -> tuple[CirculationRegion, Vec2]:
    opening = design.room.openings[opening_index]
    wall = next(wall for wall in design.room.walls if wall.id == opening.wallId)
    along, inward, midpoint = _wall_basis(design.room, wall)
    wall_centre = (
        midpoint[0] + along[0] * opening.offsetAlongWallM,
        midpoint[1] + along[1] * opening.offsetAlongWallM,
    )
    half_width = opening.widthM / 2
    corners = (
        (wall_centre[0] - along[0] * half_width, wall_centre[1] - along[1] * half_width),
        (wall_centre[0] + along[0] * half_width, wall_centre[1] + along[1] * half_width),
        (
            wall_centre[0] + along[0] * half_width + inward[0] * clearance_width_m,
            wall_centre[1] + along[1] * half_width + inward[1] * clearance_width_m,
        ),
        (
            wall_centre[0] - along[0] * half_width + inward[0] * clearance_width_m,
            wall_centre[1] - along[1] * half_width + inward[1] * clearance_width_m,
        ),
    )
    target = (
        wall_centre[0] + inward[0] * clearance_width_m / 2,
        wall_centre[1] + inward[1] * clearance_width_m / 2,
    )
    return CirculationRegion(
        id=f"door:{opening.id}",
        ownerType="door",
        ownerId=opening.id,
        corners=corners,
    ), target


def _product_regions(design: SolvedDesign, clearance_width_m: float) -> tuple[tuple[CirculationRegion, Vec2], ...]:
    values: list[tuple[CirculationRegion, Vec2]] = []
    for intent, product, placement in zip(design.intents, design.products, design.placements, strict=True):
        centre = (placement.position[0], placement.position[2])
        required_index = 0
        for region in product.accessRegions:
            if not region.required:
                continue
            footprint = access_footprint(product, region, centre, placement.yaw)
            normal = face_normal(region.face, placement.yaw)
            target_distance = face_half_extent_m(product, region.face) + max(region.depthM, clearance_width_m) / 2
            target = (
                centre[0] + normal[0] * target_distance,
                centre[1] + normal[1] * target_distance,
            )
            values.append((CirculationRegion(
                id=f"product:{intent.id}:{required_index}",
                ownerType="product",
                ownerId=intent.id,
                corners=footprint.corners,
            ), target))
            required_index += 1
    return tuple(values)


def validate_circulation(
    design: SolvedDesign,
    clearance_width_m: float,
    *,
    anchor_ids: frozenset[str] = frozenset(),
) -> CirculationResultValue:
    """Connect every required door/Product access region with a swept square."""
    half = clearance_width_m / 2
    xs = [point[0] for point in design.room.floorPolygon]
    zs = [point[1] for point in design.room.floorPolygon]
    low_x, high_x = min(xs) + half, max(xs) - half
    low_z, high_z = min(zs) + half, max(zs) - half
    x_count = max(0, floor((high_x - low_x) / GRID_RESOLUTION_M + 1e-9) + 1)
    z_count = max(0, floor((high_z - low_z) / GRID_RESOLUTION_M + 1e-9) + 1)
    raw_count = x_count * z_count

    # This gate precedes obstacle creation, access polygon scans and allocation.
    # A huge Room cannot hide behind a small number of valid/free nodes.
    if (
        x_count > MAX_LATTICE_POINTS_PER_AXIS
        or z_count > MAX_LATTICE_POINTS_PER_AXIS
        or raw_count > MAX_RAW_LATTICE_POINTS
    ):
        return CirculationUnsupported(
            status="CIRCULATION_UNSUPPORTED",
            detail=(
                f"The raw {x_count} by {z_count} circulation lattice has {raw_count} candidate nodes; "
                f"limits are {MAX_LATTICE_POINTS_PER_AXIS} per axis and {MAX_RAW_LATTICE_POINTS} total"
            ),
            clearanceWidthM=clearance_width_m,
            accessRegions=(),
            gridResolutionM=GRID_RESOLUTION_M,
            nodeLimit=MAX_RAW_LATTICE_POINTS,
            exhaustive=False,
        )

    obstacles = tuple(
        (
            placement.instanceId or intent.id,
            footprint_of(product, (placement.position[0], placement.position[2]), placement.yaw).corners,
        )
        for intent, product, placement in zip(design.intents, design.products, design.placements, strict=True)
        if product.placementClass != "floor-covering"
    )
    door_values = tuple(
        _door_region(design, index, clearance_width_m)
        for index, opening in enumerate(design.room.openings)
        if opening.kind == "door"
    )
    access_values = tuple(sorted(
        (*door_values, *_product_regions(design, clearance_width_m)),
        key=lambda value: value[0].id,
    ))
    access_regions = tuple(value[0] for value in access_values)
    if not access_values:
        return CirculationClear(
            status="clear",
            clearanceWidthM=clearance_width_m,
            accessRegions=(),
            gridResolutionM=GRID_RESOLUTION_M,
            validatedNodes=0,
            exhaustive=False,
        )

    narrow_doors = {
        f"door:{opening.id}"
        for opening in design.room.openings
        if opening.kind == "door" and opening.widthM + CIRCULATION_TOLERANCE_M < clearance_width_m
    }
    valid_grid: dict[tuple[int, int], Vec2] = {}
    for z_index in range(z_count):
        z = round(low_z + z_index * GRID_RESOLUTION_M, 9)
        for x_index in range(x_count):
            x = round(low_x + x_index * GRID_RESOLUTION_M, 9)
            polygon = _walker_polygon((x, z), clearance_width_m)
            if _inside_room(design, polygon) and not _collisions(polygon, obstacles):
                valid_grid[(x_index, z_index)] = (x, z)

    def swept_free(start: Vec2, end: Vec2) -> bool:
        polygon = _swept_polygon(start, end, clearance_width_m)
        return _inside_room(design, polygon) and not _collisions(polygon, obstacles)

    connectors: dict[str, tuple[tuple[int, int], ...]] = {}
    for region, target in access_values:
        if region.id in narrow_doors:
            connectors[region.id] = ()
            continue
        target_polygon = _walker_polygon(target, clearance_width_m)
        if not _inside_room(design, target_polygon) or _collisions(target_polygon, obstacles):
            connectors[region.id] = ()
            continue
        nearest = sorted(
            valid_grid.items(),
            key=lambda item: (hypot(item[1][0] - target[0], item[1][1] - target[1]), item[0][1], item[0][0]),
        )[:16]
        connectors[region.id] = tuple(
            key
            for key, point in nearest
            if hypot(point[0] - target[0], point[1] - target[1]) <= GRID_RESOLUTION_M * 3 + 1e-9
            and swept_free(target, point)
        )

    start_region = next((region.id for region, _target in access_values if connectors[region.id]), None)
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque(connectors[start_region] if start_region is not None else ())
    edge_cache: dict[tuple[tuple[int, int], tuple[int, int]], bool] = {}
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for delta_x, delta_z in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbour = (current[0] + delta_x, current[1] + delta_z)
            if neighbour in visited or neighbour not in valid_grid:
                continue
            edge = tuple(sorted((current, neighbour)))
            allowed = edge_cache.get(edge)
            if allowed is None:
                allowed = swept_free(valid_grid[current], valid_grid[neighbour])
                edge_cache[edge] = allowed
            if allowed:
                queue.append(neighbour)

    disconnected = tuple(
        region.id
        for region, _target in access_values
        if not connectors[region.id] or not any(key in visited for key in connectors[region.id])
    )
    if not disconnected:
        return CirculationClear(
            status="clear",
            clearanceWidthM=clearance_width_m,
            accessRegions=access_regions,
            gridResolutionM=GRID_RESOLUTION_M,
            validatedNodes=len(valid_grid),
            exhaustive=False,
        )

    detected: set[str] = set()
    for current in visited:
        for delta_x, delta_z in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbour = (current[0] + delta_x, current[1] + delta_z)
            if not (0 <= neighbour[0] < x_count and 0 <= neighbour[1] < z_count):
                continue
            neighbour_point = (
                round(low_x + neighbour[0] * GRID_RESOLUTION_M, 9),
                round(low_z + neighbour[1] * GRID_RESOLUTION_M, 9),
            )
            if neighbour not in valid_grid:
                polygon = _walker_polygon(neighbour_point, clearance_width_m)
            else:
                edge = tuple(sorted((current, neighbour)))
                if edge_cache.get(edge, True):
                    continue
                polygon = _swept_polygon(valid_grid[current], neighbour_point, clearance_width_m)
            detected.update(_collisions(polygon, obstacles))

    movable_nonanchors = {
        placement.instanceId or intent.id
        for intent, placement in zip(design.intents, design.placements, strict=True)
        if (placement.instanceId or intent.id) not in anchor_ids
    }
    implicated = tuple(sorted(detected | movable_nonanchors))
    connector_failures = tuple(access_id for access_id in disconnected if not connectors[access_id])
    if connector_failures:
        limitation = (
            "At least one disconnected access has no usable clearance-grid connector; "
            "the conservative frontier cannot establish unique Product causality. "
            "All movable non-anchor requests are included."
        )
    else:
        limitation = (
            "The conservative grid frontier identifies nearby obstacles but cannot establish unique Product causality; "
            "all movable non-anchor requests are included."
        )
    narrow_detail = (
        f" Door approach width is below {clearance_width_m:.2f} m for {', '.join(sorted(narrow_doors))}."
        if narrow_doors else ""
    )
    return CirculationBlocked(
        status="CIRCULATION_BLOCKED",
        detail=(
            f"Required access is not connected for {', '.join(disconnected)} at {clearance_width_m:.2f} m clearance."
            f"{narrow_detail}"
        ),
        clearanceWidthM=clearance_width_m,
        accessRegions=access_regions,
        disconnectedAccessIds=disconnected,
        implicatedRequestIds=implicated,
        attributionLimited=True,
        attributionLimitation=limitation,
        gridResolutionM=GRID_RESOLUTION_M,
        validatedNodes=len(valid_grid),
        exhaustive=False,
    )
