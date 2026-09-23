from __future__ import annotations

from copy import deepcopy
from math import pi

import pytest
from pydantic import ValidationError

import api.circulation as circulation_module
import api.domain as domain_module
from api.arrangement import plan_optional_drop, resolve_arrangement
from api.catalogue import CatalogueEntry, StaticCatalogue, catalogue
from api.circulation import validate_circulation
from api.design import FEATURED_PRODUCT_ID, resolve_fixture, zoned_fixture_room
from api.domain import rectangular_room_shell, resolve_design, validate_placement
from api.models import (
    ArrangementRequest,
    DesignRequest,
    FixtureSelectionRequest,
    Placement,
    PlacementIntent,
    Product,
    RoomShell,
    SearchReport,
    SolvedDesign,
)
from api.zones import derive_zones


def product_variant(
    product_id: str,
    *,
    width: float,
    depth: float,
    placement_class: str = "floor-standing",
    access_regions: list[dict] | None = None,
    contact_faces: list[str] | None = None,
) -> Product:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    value = deepcopy(base.model_dump(mode="json"))
    value.update({
        "id": product_id,
        "displayName": product_id,
        "dimensionsM": {"widthM": width, "heightM": 0.5, "depthM": depth},
        "placementClass": placement_class,
        "accessRegions": access_regions or [],
        "wallContactFaces": contact_faces or ["back", "front", "left", "right"],
    })
    return Product.model_validate(value)


def static_catalogue(*products: Product) -> StaticCatalogue:
    return StaticCatalogue("ticket-5-tests", [
        CatalogueEntry(product=product, private_style_ids=("fixture-style",))
        for product in products
    ])


def room_with_two_doors(width: float = 4.0, depth: float = 6.0) -> RoomShell:
    value = rectangular_room_shell("circulation-room", width, depth, 3).model_dump(mode="json")
    value["openings"] = [
        {
            "id": "north-door",
            "kind": "door",
            "wallId": "wall-north",
            "offsetAlongWallM": 0,
            "widthM": 1,
            "bottomM": 0,
            "heightM": 2.1,
            "clearanceDepthM": 0,
            "doorSwing": {"hingeSide": "start"},
        },
        {
            "id": "south-door",
            "kind": "door",
            "wallId": "wall-south",
            "offsetAlongWallM": 0,
            "widthM": 1,
            "bottomM": 0,
            "heightM": 2.1,
            "clearanceDepthM": 0,
            "doorSwing": {"hingeSide": "end"},
        },
    ]
    return RoomShell.model_validate(value)


def convex_room(room_id: str, points: list[tuple[float, float]]) -> RoomShell:
    return RoomShell.model_validate({
        "id": room_id,
        "floorPolygon": points,
        "walls": [
            {
                "id": f"wall-{index}",
                "label": f"Wall {index}",
                "start": point,
                "end": points[(index + 1) % len(points)],
            }
            for index, point in enumerate(points)
        ],
        "openings": [],
        "ceilingHeightM": 3,
    })


def solved_from_placements(
    room: RoomShell,
    products: tuple[Product, ...],
    placements: tuple[Placement, ...],
) -> SolvedDesign:
    intents = tuple(
        PlacementIntent(id=placement.instanceId or f"request-{index}", kind="fixture", productId=product.id)
        for index, (product, placement) in enumerate(zip(products, placements, strict=True))
    )
    fits = []
    occupied: list[tuple[Product, Placement]] = []
    for product, placement in zip(products, placements, strict=True):
        fit = validate_placement(product, room, placement, occupied=tuple(occupied))
        assert fit.status == "fits", fit
        fits.append(fit)
        occupied.append((product, placement))
    return SolvedDesign(
        status="solved",
        room=room,
        intents=intents,
        products=products,
        placements=placements,
        fits=tuple(fits),
        search=SearchReport(attemptedCandidates=len(placements), candidateLimit=256, exhaustive=True),
    )


def throat_design(gap_m: float) -> SolvedDesign:
    room = room_with_two_doors()
    obstacle_width = (4.0 - gap_m) / 2
    left = product_variant("left-obstacle", width=obstacle_width, depth=0.5)
    right = product_variant("right-obstacle", width=obstacle_width, depth=0.5)
    return solved_from_placements(
        room,
        (left, right),
        (
            Placement(instanceId="left", productId=left.id, position=(-2 + obstacle_width / 2, 0, 0), yaw=0),
            Placement(instanceId="right", productId=right.id, position=(2 - obstacle_width / 2, 0, 0), yaw=0),
        ),
    )


def test_zone_derivation_matches_worked_opening_exclusion_and_stable_ids() -> None:
    room = zoned_fixture_room()
    offer = derive_zones(room)

    assert [zone.bounds.model_dump() for zone in offer.zones] == pytest.approx([
        {"minX": -2.4, "minZ": -4.0, "maxX": 2.4, "maxZ": 2.998794004},
        {"minX": -2.4, "minZ": 2.998794004, "maxX": -0.501205996, "maxZ": 4.0},
        {"minX": 0.5, "minZ": 2.998794004, "maxX": 2.4, "maxZ": 4.0},
    ], abs=1e-8)

    reordered = room.model_dump(mode="json")
    reordered["walls"] = list(reversed(reordered["walls"]))
    reordered["openings"] = list(reversed(reordered["openings"]))
    repeated = derive_zones(RoomShell.model_validate(reordered))
    assert repeated.model_dump_json() == offer.model_dump_json()

    multiple = room.model_dump(mode="json")
    multiple["openings"].append({
        "id": "north-window",
        "kind": "window",
        "wallId": "wall-north",
        "offsetAlongWallM": 1.2,
        "widthM": 0.8,
        "bottomM": 1.0,
        "heightM": 1.0,
        "clearanceDepthM": 0.35,
    })
    forward = derive_zones(RoomShell.model_validate(multiple))
    multiple["openings"].reverse()
    backward = derive_zones(RoomShell.model_validate(multiple))
    assert forward.model_dump_json() == backward.model_dump_json()


def test_short_bevel_never_offers_the_nonrectangular_room_bounding_box() -> None:
    points = [(-3, -3), (-3, 3), (2.99, 3), (3, 2.99), (3, -3)]
    room = RoomShell.model_validate({
        "id": "bevel-oracle",
        "floorPolygon": points,
        "ceilingHeightM": 3,
        "walls": [{
            "id": f"wall-{index}",
            "label": f"Wall {index}",
            "start": point,
            "end": points[(index + 1) % len(points)],
        } for index, point in enumerate(points)],
    })

    offer = derive_zones(room)

    assert offer.zones
    for zone in offer.zones:
        bounds = zone.bounds
        for x, z in (
            (bounds.minX, bounds.minZ),
            (bounds.minX, bounds.maxZ),
            (bounds.maxX, bounds.minZ),
            (bounds.maxX, bounds.maxZ),
        ):
            assert (x + z - 5.99) / 2**0.5 <= 0.001 + 1e-9
    assert all(not (zone.bounds.maxX == 3 and zone.bounds.maxZ == 3) for zone in offer.zones)


def test_zone_http_returns_typed_unsupported_before_large_subdivision(client) -> None:
    room = rectangular_room_shell("large-zone-room", 40, 40, 3)
    response = client.post("/api/zones", json={"room": room.model_dump(mode="json")})

    assert response.status_code == 200
    assert response.json()["status"] == "ZONE_DERIVATION_UNSUPPORTED"
    assert "supported limit is 128" in response.json()["detail"]


def test_in_zone_uses_only_offered_ids_and_checks_boundary_and_size() -> None:
    room = rectangular_room_shell("two-metre-room", 2, 2, 2.5)
    zone = derive_zones(room).zones[0]
    exact = product_variant("exact-zone-product", width=2, depth=2)
    too_large = product_variant("oversized-zone-product", width=2.01, depth=2)
    source = static_catalogue(exact, too_large)

    solved = resolve_design(source, DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{"id": "exact", "kind": "in_zone", "productId": exact.id, "zoneId": zone.id}],
        "maxCandidates": 16,
    }))
    assert solved.status == "solved"
    assert solved.placements[0].position == pytest.approx((0, 0, 0), abs=1e-9)
    assert solved.zones == (zone,)

    unknown = resolve_design(source, DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{"id": "unknown", "kind": "in_zone", "productId": exact.id, "zoneId": "invented"}],
    }))
    assert unknown.status == "failed"
    assert unknown.reason == "unknown-zone-reference"
    assert unknown.search.attemptedCandidates == 0

    oversized = resolve_design(source, DesignRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "intents": [{"id": "large", "kind": "in_zone", "productId": too_large.id, "zoneId": zone.id}],
        "maxCandidates": 16,
    }))
    assert oversized.status == "failed"
    assert oversized.reason == "intent-unsatisfiable"
    assert oversized.search.attemptedCandidates == 0


@pytest.mark.parametrize(
    ("gap_m", "expected_status"),
    ((0.599, "CIRCULATION_BLOCKED"), (0.600, "clear"), (0.601, "clear")),
)
def test_swept_clearance_distinguishes_throats_at_and_around_060m(gap_m: float, expected_status: str) -> None:
    result = validate_circulation(throat_design(gap_m), 0.60)
    assert result.status == expected_status


def test_circulation_prepares_each_invariant_wall_normal_once(monkeypatch) -> None:
    design = throat_design(0.600)
    baseline = circulation_module.validate_circulation(design, 0.60)
    original = domain_module.wall_inward_normal
    prepared_wall_ids: list[str] = []

    def counted(room: RoomShell, wall):
        prepared_wall_ids.append(wall.id)
        return original(room, wall)

    monkeypatch.setattr(domain_module, "wall_inward_normal", counted)
    result = circulation_module.validate_circulation(design, 0.60)

    assert result.model_dump(mode="json") == baseline.model_dump(mode="json")
    expected_door_wall_ids = [
        opening.wallId for opening in design.room.openings if opening.kind == "door"
    ]
    assert prepared_wall_ids == [wall.id for wall in design.room.walls] + expected_door_wall_ids


def test_prepared_room_containment_exactly_matches_prior_formula_across_geometry_boundaries() -> None:
    rectangle = rectangular_room_shell("parity-rectangle", 4, 6, 3)
    diamond_points = [(0.0, -3.0), (-3.0, 0.0), (0.0, 3.0), (3.0, 0.0)]
    pentagon_points = [(-3.0, -2.0), (-3.0, 1.0), (0.0, 3.0), (3.0, 1.0), (3.0, -2.0)]
    translated_points = [(97.0, 198.0), (97.0, 202.0), (103.0, 202.0), (103.0, 198.0)]
    rooms = (
        rectangle,
        convex_room("parity-diamond", diamond_points),
        convex_room("parity-pentagon", pentagon_points),
        convex_room("parity-pentagon-reversed", list(reversed(pentagon_points))),
        convex_room("parity-translated", translated_points),
    )

    def prior_formula(room: RoomShell, polygon) -> bool:
        if len(polygon) == 4:
            footprint = circulation_module._polygon_footprint(polygon)
            return domain_module._clearance(room, footprint) >= -circulation_module.CIRCULATION_TOLERANCE_M
        return all(
            min(
                (point[0] - wall.start[0]) * inward[0] + (point[1] - wall.start[1]) * inward[1]
                for wall in room.walls
                for _along, inward, _midpoint in (domain_module._wall_basis(room, wall),)
            ) >= -circulation_module.CIRCULATION_TOLERANCE_M
            for point in polygon
        )

    for room in rooms:
        centre = (
            sum(point[0] for point in room.floorPolygon) / len(room.floorPolygon),
            sum(point[1] for point in room.floorPolygon) / len(room.floorPolygon),
        )
        polygons = (
            circulation_module._walker_polygon(centre, 0.60),
            circulation_module._swept_polygon(
                (centre[0] - 0.20, centre[1] - 0.20),
                (centre[0] + 0.20, centre[1] + 0.20),
                0.60,
            ),
            circulation_module._walker_polygon(
                (max(point[0] for point in room.floorPolygon) + 1, centre[1]),
                0.60,
            ),
        )
        prepared = circulation_module._prepare_room_geometry(room)
        for polygon in polygons:
            assert circulation_module._inside_prepared_room(prepared, polygon) is prior_formula(room, polygon)

    low_x = min(point[0] for point in rectangle.floorPolygon)
    for outside_delta in (0.5e-9, 1e-9, 2e-9):
        polygon = (
            (low_x - outside_delta, -0.1),
            (low_x + 0.2, -0.1),
            (low_x + 0.2, 0.1),
            (low_x - outside_delta, 0.1),
        )
        prepared = circulation_module._prepare_room_geometry(rectangle)
        assert circulation_module._inside_prepared_room(prepared, polygon) is prior_formula(rectangle, polygon)


def test_ambiguous_reachable_boundary_has_stable_conservative_attribution() -> None:
    design = throat_design(0.599)
    result = validate_circulation(design, 0.60, anchor_ids=frozenset({"left"}))

    assert result.status == "CIRCULATION_BLOCKED"
    assert result.disconnectedAccessIds == ("door:south-door",)
    assert result.attributionLimited is True
    assert result.attributionLimitation is not None
    assert result.implicatedRequestIds == ("left", "right")
    assert result.gridResolutionM == 0.05
    assert result.exhaustive is False


def test_floor_covering_is_walkable_without_deleting_its_required_access() -> None:
    room = room_with_two_doors()
    rug = product_variant(
        "walkable-rug",
        width=4,
        depth=1,
        placement_class="floor-covering",
        access_regions=[{
            "face": "front",
            "depthM": 0.6,
            "required": True,
            "purpose": "reaching the rug edge",
        }],
    )
    rotated = product_variant("rotated-chair", width=0.4, depth=0.4)
    design = solved_from_placements(
        room,
        (rug, rotated),
        (
            Placement(instanceId="rug", productId=rug.id, position=(0, 0, 0), yaw=0),
            Placement(instanceId="rotated", productId=rotated.id, position=(1.4, 0, 1.5), yaw=pi / 4),
        ),
    )

    result = validate_circulation(design, 0.60)

    assert result.status == "clear"
    assert "product:rug:0" in [region.id for region in result.accessRegions]


def test_rotated_obstacle_uses_its_actual_footprint_for_the_swept_path() -> None:
    room = room_with_two_doors()
    rotated_barrier = product_variant("rotated-barrier", width=0.5, depth=4.0)
    design = solved_from_placements(
        room,
        (rotated_barrier,),
        (Placement(instanceId="rotated-barrier", productId=rotated_barrier.id, position=(0, 0, 0), yaw=pi / 2),),
    )

    result = validate_circulation(design, 0.60)

    assert result.status == "CIRCULATION_BLOCKED"
    assert result.implicatedRequestIds == ("rotated-barrier",)


def test_actual_door_width_below_clearance_is_blocked() -> None:
    room_value = room_with_two_doors().model_dump(mode="json")
    room_value["openings"][1]["widthM"] = 0.599
    design = solved_from_placements(RoomShell.model_validate(room_value), (), ())

    result = validate_circulation(design, 0.60)

    assert result.status == "CIRCULATION_BLOCKED"
    assert "door:south-door" in result.disconnectedAccessIds
    assert "below 0.60 m" in result.detail


def test_unusable_door_connector_never_uniquely_blames_an_unrelated_singleton() -> None:
    unrelated = product_variant("unrelated-centre-box", width=0.4, depth=0.4)
    placement = Placement(
        instanceId=unrelated.id,
        productId=unrelated.id,
        position=(0, 0, 0),
        yaw=0,
    )

    narrow_value = room_with_two_doors(width=6, depth=6).model_dump(mode="json")
    narrow_value["openings"][1]["widthM"] = 0.5
    narrow_room = RoomShell.model_validate(narrow_value)
    narrow_with_box = validate_circulation(
        solved_from_placements(narrow_room, (unrelated,), (placement,)),
        0.60,
    )
    narrow_without_box = validate_circulation(solved_from_placements(narrow_room, (), ()), 0.60)

    wide_value = deepcopy(narrow_value)
    wide_value["openings"][1]["widthM"] = 1.0
    wide_room = RoomShell.model_validate(wide_value)
    wide_with_box = validate_circulation(
        solved_from_placements(wide_room, (unrelated,), (placement,)),
        0.60,
    )

    assert narrow_with_box.status == "CIRCULATION_BLOCKED"
    assert narrow_with_box.disconnectedAccessIds == ("door:south-door",)
    assert narrow_with_box.implicatedRequestIds == ("unrelated-centre-box",)
    assert narrow_with_box.attributionLimited is True
    assert "no usable clearance-grid connector" in narrow_with_box.attributionLimitation
    assert narrow_without_box.status == "CIRCULATION_BLOCKED"
    assert narrow_without_box.implicatedRequestIds == ()
    assert narrow_without_box.attributionLimited is True
    assert wide_with_box.status == "clear"


def test_raw_lattice_is_bounded_before_obstacle_polygon_scans(monkeypatch) -> None:
    huge_room = rectangular_room_shell("huge-room", 100, 100, 3)
    obstacle = product_variant("huge-room-obstacle", width=1, depth=1)
    design = solved_from_placements(
        huge_room,
        (obstacle,),
        (Placement(instanceId="obstacle", productId=obstacle.id, position=(0, 0, 0), yaw=0),),
    )
    monkeypatch.setattr("api.circulation.footprint_of", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("polygon scan ran")))

    result = validate_circulation(design, 0.60)

    assert result.status == "CIRCULATION_UNSUPPORTED"
    assert "raw" in result.detail
    assert result.nodeLimit == 50_000


def test_fixture_arrangements_expose_repair_and_exhaustion_history() -> None:
    repaired = resolve_fixture(FixtureSelectionRequest(fixtureId="zoned-repairable"))
    assert repaired.status == "solved"
    assert [attempt.outcome for attempt in repaired.arrangementHistory.attempts] == [
        "circulation-blocked",
        "solved",
    ]
    assert repaired.arrangementHistory.attempts[1].changedRequestIds == ("c-barrier-right",)
    assert [placement.instanceId for placement in repaired.placements] == [
        "a-bed",
        "b-barrier-left",
        "c-barrier-right",
        "z-zone-rug",
    ]
    assert repaired.circulation.status == "clear"

    exhausted = resolve_fixture(FixtureSelectionRequest(fixtureId="zoned-exhausted"))
    assert exhausted.status == "failed"
    assert exhausted.reason == "NO_VALID_DESIGN"
    assert exhausted.limitingConstraint.code == "CIRCULATION_BLOCKED"
    assert exhausted.limitingConstraint.attributionLimited is True
    assert exhausted.limitingConstraint.attributionLimitation
    assert exhausted.limitingConstraint.gridResolutionM == 0.05
    assert [attempt.stage for attempt in exhausted.arrangementHistory.attempts] == [
        "initial",
        "repair",
        "repair",
        "drop",
    ]
    assert exhausted.arrangementHistory.attempts[-1].droppedRequestIds == ("z-zone-rug",)
    assert exhausted.arrangementHistory.totalAttemptedCandidates <= 4 * 256


def test_request_policy_rejects_anchor_mutation_and_identity_churn() -> None:
    room = rectangular_room_shell("policy-room", 3, 3, 2.5)
    initial = {"id": "anchor", "kind": "centred_on", "productId": FEATURED_PRODUCT_ID, "wallId": "wall-north"}
    body = {
        "room": room.model_dump(mode="json"),
        "selections": [
            {"id": "initial", "intents": [initial]},
            {"id": "repair", "intents": [{**initial, "wallId": "wall-south"}]},
        ],
        "policies": [{"requestId": "anchor", "required": True, "anchor": True}],
        "clearanceWidthM": 0.6,
    }
    with pytest.raises(ValidationError, match="may not change required or anchor"):
        ArrangementRequest.model_validate(body)

    body["selections"][1]["intents"] = [{**initial, "id": "replacement"}]
    with pytest.raises(ValidationError, match="preserve the initial request identity"):
        ArrangementRequest.model_validate(body)


def test_drop_plan_expands_dependency_chain_and_complete_flanking_pair_by_identity() -> None:
    intents = tuple(PlacementIntent.model_validate(value) for value in (
        {"id": "root", "kind": "centred_on", "productId": "duplicate", "wallId": "wall-north"},
        {"id": "child", "kind": "adjacent_to", "productId": "duplicate", "referenceId": "root", "side": "right"},
        {"id": "grandchild", "kind": "adjacent_to", "productId": "duplicate", "referenceId": "child", "side": "front"},
        {"id": "flank-left", "kind": "flanking", "productId": "duplicate", "referenceId": "child", "side": "left"},
        {"id": "flank-right", "kind": "flanking", "productId": "duplicate", "referenceId": "child", "side": "right"},
        {"id": "unrelated", "kind": "centred_on", "productId": "duplicate", "wallId": "wall-south"},
    ))

    plan = plan_optional_drop(intents, "root")
    assert plan.safe is True
    assert plan.closure == frozenset({"root", "child", "grandchild", "flank-left", "flank-right"})
    assert "unrelated" not in plan.closure

    unsafe = plan_optional_drop(intents, "root", protected_ids=frozenset({"grandchild"}))
    assert unsafe.safe is False
    assert unsafe.protected_ids == frozenset({"grandchild"})


def test_optional_only_arrangement_returns_bounded_no_valid_design_at_python_and_http(client) -> None:
    room = rectangular_room_shell("optional-only-room", 1, 1, 2.5)
    zone = derive_zones(room).zones[0]
    request_body = {
        "room": room.model_dump(mode="json"),
        "selections": [{
            "id": "initial",
            "intents": [{
                "id": "only-optional",
                "kind": "in_zone",
                "productId": FEATURED_PRODUCT_ID,
                "zoneId": zone.id,
            }],
        }],
        "policies": [{
            "requestId": "only-optional",
            "required": False,
            "anchor": False,
            "optionalKind": "decoration",
        }],
        "clearanceWidthM": 0.6,
        "maxCandidates": 16,
    }
    python_result = resolve_arrangement(catalogue, ArrangementRequest.model_validate(request_body))
    assert python_result.status == "failed"
    assert python_result.reason == "NO_VALID_DESIGN"
    assert python_result.limitingConstraint.code == "EMPTY_DESIGN_NOT_SUPPORTED"
    assert python_result.arrangementHistory.attempts[-1].attemptedCandidates == 0

    response = client.post("/api/arrangement-solve", json=request_body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["reason"] == "NO_VALID_DESIGN"
    assert payload["limitingConstraint"]["code"] == "EMPTY_DESIGN_NOT_SUPPORTED"


def test_optional_drop_priority_is_decoration_then_secondary_then_stable_id() -> None:
    room = rectangular_room_shell("drop-priority-room", 1, 1, 2.5)
    zone = derive_zones(room).zones[0]
    request = ArrangementRequest.model_validate({
        "room": room.model_dump(mode="json"),
        "selections": [{
            "id": "initial",
            "intents": [
                {"id": "a-secondary", "kind": "in_zone", "productId": FEATURED_PRODUCT_ID, "zoneId": zone.id},
                {"id": "z-decoration", "kind": "in_zone", "productId": FEATURED_PRODUCT_ID, "zoneId": zone.id},
            ],
        }],
        "policies": [
            {"requestId": "a-secondary", "required": False, "anchor": False, "optionalKind": "secondary-furniture"},
            {"requestId": "z-decoration", "required": False, "anchor": False, "optionalKind": "decoration"},
        ],
        "clearanceWidthM": 0.6,
        "maxCandidates": 16,
    })

    result = resolve_arrangement(catalogue, request)

    assert result.status == "failed"
    drop_attempts = [attempt for attempt in result.arrangementHistory.attempts if attempt.stage == "drop"]
    assert drop_attempts[0].droppedRequestIds == ("z-decoration",)
    assert drop_attempts[1].droppedRequestIds == ("a-secondary", "z-decoration")
    assert drop_attempts[1].limitingConstraint.code == "EMPTY_DESIGN_NOT_SUPPORTED"


def test_http_preserves_ambiguous_attribution_limit_and_invalid_room_is_separate(client) -> None:
    exhausted = client.post("/api/design-resolution", json={"fixtureId": "zoned-exhausted"})
    assert exhausted.status_code == 200
    constraint = exhausted.json()["limitingConstraint"]
    assert constraint["code"] == "CIRCULATION_BLOCKED"
    assert constraint["attributionLimited"] is True
    assert constraint["attributionLimitation"]
    assert constraint["gridResolutionM"] == 0.05

    invalid_room = client.post("/api/arrangement-solve", json={
        "room": {
            "id": "invalid",
            "floorPolygon": [[0, 0], [0, 1], [1, 0], [1, 1]],
            "walls": [],
            "ceilingHeightM": 2.5,
        },
        "selections": [],
        "policies": [],
        "clearanceWidthM": 0.6,
    })
    assert invalid_room.status_code == 422
    assert invalid_room.json()["detail"]
