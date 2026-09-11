from __future__ import annotations

from copy import deepcopy
from math import pi

import pytest

from api.catalogue import CatalogueEntry, StaticCatalogue
from api.domain import resolve_design, validate_placement
from api.models import DesignRequest, Placement, Product


def product_variant(
    product: Product,
    product_id: str,
    *,
    width: float,
    depth: float,
    height: float = 1.0,
    placement_class: str = "floor-standing",
    contact_faces: list[str] | None = None,
    access_regions: list[dict] | None = None,
) -> Product:
    value = deepcopy(product.model_dump(mode="json"))
    value.update({
        "id": product_id,
        "displayName": product_id,
        "dimensionsM": {"widthM": width, "heightM": height, "depthM": depth},
        "placementClass": placement_class,
        "wallContactFaces": contact_faces or [],
        "accessRegions": access_regions or [],
    })
    return Product.model_validate(value)


def make_catalogue(*products: Product) -> StaticCatalogue:
    return StaticCatalogue("object-relative-test", [
        CatalogueEntry(product=product, private_style_ids=("fixture-style",))
        for product in products
    ])


def room_body() -> dict:
    points = [[-5, -5], [-5, 5], [5, 5], [5, -5]]
    return {
        "id": "oracle-room",
        "floorPolygon": points,
        "ceilingHeightM": 3,
        "walls": [
            {"id": wall_id, "label": wall_id, "start": points[index], "end": points[(index + 1) % 4]}
            for index, wall_id in enumerate(("west", "south", "east", "north"))
        ],
        "openings": [],
    }


def solve(source: StaticCatalogue, intents: list[dict], *, room: dict | None = None, limit: int = 256):
    return resolve_design(source, DesignRequest.model_validate({
        "room": room or room_body(),
        "intents": intents,
        "maxCandidates": limit,
    }))


@pytest.mark.parametrize(
    "wall_id,anchor_position,anchor_yaw,adjacent_position,facing_position,facing_yaw",
    [
        ("north", (0, 0, -4), 0, (1.85, 0, -4), (0, 0, -1.75), pi),
        ("east", (4, 0, 0), -pi / 2, (4, 0, 1.85), (1.75, 0, 0), pi / 2),
    ],
)
def test_relative_geometry_matches_the_rotated_host_oracle_and_input_order_is_public_only(
    product: Product,
    wall_id: str,
    anchor_position: tuple[float, float, float],
    anchor_yaw: float,
    adjacent_position: tuple[float, float, float],
    facing_position: tuple[float, float, float],
    facing_yaw: float,
) -> None:
    anchor = product_variant(product, "anchor", width=2, depth=2, contact_faces=["back"])
    small = product_variant(product, "small", width=0.5, depth=0.5)
    intents = [
        {"id": "anchor-request", "kind": "centred_on", "productId": anchor.id, "wallId": wall_id},
        {"id": "right-request", "kind": "adjacent_to", "productId": small.id, "referenceId": "anchor-request", "side": "right", "gapM": 0.6},
        {"id": "facing-request", "kind": "facing", "productId": small.id, "referenceId": "anchor-request", "gapM": 1.0},
    ]

    forward = solve(make_catalogue(anchor, small), intents)
    reversed_input = solve(make_catalogue(anchor, small), list(reversed(intents)))

    assert forward.status == reversed_input.status == "solved"
    assert [intent.id for intent in reversed_input.intents] == ["facing-request", "right-request", "anchor-request"]
    expected = {
        "anchor-request": (anchor_position, anchor_yaw),
        "right-request": (adjacent_position, anchor_yaw),
        "facing-request": (facing_position, facing_yaw),
    }
    for result in (forward, reversed_input):
        actual = {placement.instanceId: (placement.position, placement.yaw) for placement in result.placements}
        for instance_id, (position, yaw) in expected.items():
            assert actual[instance_id][0] == pytest.approx(position, abs=1e-9)
            assert actual[instance_id][1] == pytest.approx(yaw, abs=1e-9)


def test_request_chain_uses_resolved_target_frames_and_survives_reversed_input(product: Product) -> None:
    anchor = product_variant(product, "chain-anchor", width=2, depth=2, contact_faces=["back"])
    small = product_variant(product, "chain-small", width=0.5, depth=0.5)
    intents = [
        {"id": "a", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        {"id": "b", "kind": "adjacent_to", "productId": small.id, "referenceId": "a", "side": "right", "gapM": 0.6},
        {"id": "c", "kind": "adjacent_to", "productId": small.id, "referenceId": "b", "side": "front", "gapM": 0.5},
    ]

    result = solve(make_catalogue(anchor, small), list(reversed(intents)))

    assert result.status == "solved"
    assert [placement.instanceId for placement in result.placements] == ["c", "b", "a"]
    placements = {placement.instanceId: placement for placement in result.placements}
    assert placements["c"].position == pytest.approx((1.85, 0, -3), abs=1e-9)
    assert placements["c"].yaw == pytest.approx(0, abs=1e-9)


def test_flanking_is_two_referenceable_instances_with_shared_gap_and_rear_alignment(product: Product) -> None:
    anchor = product_variant(product, "flank-anchor", width=2, depth=2, contact_faces=["back"])
    flank = product_variant(product, "flank-small", width=0.5, depth=0.5, contact_faces=["back"])
    result = solve(make_catalogue(anchor, flank), [
        {"id": "anchor", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        {"id": "left", "kind": "flanking", "productId": flank.id, "referenceId": "anchor", "side": "left", "gapM": 0.6},
        {"id": "right", "kind": "flanking", "productId": flank.id, "referenceId": "anchor", "side": "right", "gapM": 0.6},
        {"id": "in-front-of-right", "kind": "adjacent_to", "productId": flank.id, "referenceId": "right", "side": "front", "gapM": 0.5},
    ])

    assert result.status == "solved"
    placements = {placement.instanceId: placement for placement in result.placements}
    assert placements["left"].position == pytest.approx((-1.85, 0, -4.75), abs=1e-9)
    assert placements["right"].position == pytest.approx((1.85, 0, -4.75), abs=1e-9)
    assert placements["left"].wallContact.model_dump(mode="json") == {"wallId": "north", "face": "back"}
    assert placements["right"].wallContact.model_dump(mode="json") == {"wallId": "north", "face": "back"}
    assert placements["in-front-of-right"].position == pytest.approx((1.85, 0, -3.75), abs=1e-9)


@pytest.mark.parametrize(
    "intents,reason",
    [
        ([{"id": "missing", "kind": "adjacent_to", "productId": "small", "referenceId": "nope", "side": "right"}], "unknown-intent-reference"),
        ([{"id": "self", "kind": "adjacent_to", "productId": "small", "referenceId": "self", "side": "right"}], "self-intent-reference"),
        ([
            {"id": "a", "kind": "adjacent_to", "productId": "small", "referenceId": "b", "side": "right"},
            {"id": "b", "kind": "adjacent_to", "productId": "small", "referenceId": "a", "side": "left"},
        ], "cyclic-intent-reference"),
        ([
            {"id": "anchor", "kind": "centred_on", "productId": "anchor", "wallId": "north"},
            {"id": "lonely", "kind": "flanking", "productId": "small", "referenceId": "anchor", "side": "left", "gapM": 0.6},
        ], "invalid-flanking-group"),
        ([
            {"id": "anchor", "kind": "centred_on", "productId": "anchor", "wallId": "north"},
            {"id": "left", "kind": "flanking", "productId": "small", "referenceId": "anchor", "side": "left", "gapM": 0.6},
            {"id": "right", "kind": "flanking", "productId": "small", "referenceId": "anchor", "side": "right", "gapM": 0.7},
        ], "invalid-flanking-group"),
    ],
)
def test_reference_graph_and_flanking_shape_fail_before_search(
    product: Product,
    intents: list[dict],
    reason: str,
) -> None:
    anchor = product_variant(product, "anchor", width=2, depth=2, contact_faces=["back"])
    small = product_variant(product, "small", width=0.5, depth=0.5)

    result = solve(make_catalogue(anchor, small), intents)

    assert result.status == "failed"
    assert result.reason == reason
    assert result.search.attemptedCandidates == 0


def test_whole_graph_is_validated_before_an_impossible_earlier_candidate(product: Product) -> None:
    too_large = product_variant(product, "too-large", width=20, depth=20, contact_faces=["back"])
    small = product_variant(product, "small", width=0.5, depth=0.5)

    result = solve(make_catalogue(too_large, small), [
        {"id": "impossible", "kind": "centred_on", "productId": too_large.id, "wallId": "north"},
        {"id": "bad-later", "kind": "adjacent_to", "productId": small.id, "referenceId": "missing", "side": "right"},
    ])

    assert result.status == "failed"
    assert result.reason == "unknown-intent-reference"
    assert result.failedIntentId == "bad-later"
    assert result.search.attemptedCandidates == 0


def test_negative_gap_is_limited_to_floor_covering_furniture_overlap(product: Product) -> None:
    anchor = product_variant(product, "bed", width=2, depth=2, contact_faces=["back"])
    rug = product_variant(product, "rug", width=2, depth=2, height=0.0005, placement_class="floor-covering")
    ordinary = product_variant(product, "ordinary", width=2, depth=2)
    intents = [
        {"id": "bed", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        {"id": "under-bed", "kind": "adjacent_to", "productId": rug.id, "referenceId": "bed", "side": "front", "gapM": -1},
    ]

    allowed = solve(make_catalogue(anchor, rug), intents)
    forbidden = solve(make_catalogue(anchor, ordinary), [intents[0], {**intents[1], "productId": ordinary.id}])

    assert allowed.status == "solved"
    assert allowed.placements[1].position == pytest.approx((0, 0, -3), abs=1e-9)
    assert forbidden.status == "failed"
    assert forbidden.reason == "invalid-relative-gap"
    assert forbidden.search.attemptedCandidates == 0


@pytest.mark.parametrize("wall_id,side", [("north", "front"), ("east", "right")])
def test_negative_gap_cannot_reverse_rotated_requested_side_and_exact_penetration_is_centred(
    product: Product,
    wall_id: str,
    side: str,
) -> None:
    tiny_anchor = product_variant(product, "tiny-anchor", width=0.2, depth=0.2, contact_faces=["back"])
    bed = product_variant(product, "interior-bed", width=2, depth=2)
    rug = product_variant(
        product,
        "centred-rug",
        width=2,
        depth=2,
        height=0.0005,
        placement_class="floor-covering",
    )
    large_room = room_body()
    large_room["floorPolygon"] = [[-10, -10], [-10, 10], [10, 10], [10, -10]]
    large_room["walls"] = [
        {"id": name, "label": name, "start": large_room["floorPolygon"][index], "end": large_room["floorPolygon"][(index + 1) % 4]}
        for index, name in enumerate(("west", "south", "east", "north"))
    ]
    base = [
        {"id": "wall-anchor", "kind": "centred_on", "productId": tiny_anchor.id, "wallId": wall_id},
        {"id": "bed", "kind": "adjacent_to", "productId": bed.id, "referenceId": "wall-anchor", "side": "front", "gapM": 8},
    ]
    exact = {"id": "rug", "kind": "adjacent_to", "productId": rug.id, "referenceId": "bed", "side": side, "gapM": -2}
    rounding_noise = {**exact, "gapM": -2.0000000005}
    beyond = {**exact, "gapM": -2.00001}

    solved = solve(make_catalogue(tiny_anchor, bed, rug), list(reversed([*base, exact])), room=large_room)
    rounded = solve(make_catalogue(tiny_anchor, bed, rug), [*base, rounding_noise], room=large_room)
    rejected = solve(make_catalogue(tiny_anchor, bed, rug), list(reversed([*base, beyond])), room=large_room)

    assert solved.status == "solved"
    placements = {placement.instanceId: placement for placement in solved.placements}
    assert placements["rug"].position == pytest.approx(placements["bed"].position, abs=1e-9)
    assert rounded.status == "solved"
    rounded_placements = {placement.instanceId: placement for placement in rounded.placements}
    assert rounded_placements["rug"].position == pytest.approx(rounded_placements["bed"].position, abs=1e-9)
    assert rejected.status == "failed"
    assert rejected.reason == "invalid-relative-gap"
    assert rejected.failedIntentId == "rug"
    assert rejected.search.attemptedCandidates == 0


@pytest.mark.parametrize(
    "intent",
    [
        {"id": "wall", "kind": "centred_on", "productId": "anchor", "wallId": "north", "gapM": 0.1},
        {"id": "relative", "kind": "adjacent_to", "productId": "small", "referenceId": "wall", "side": "right", "face": "front"},
    ],
)
def test_non_neutral_fields_for_the_wrong_supported_intent_shape_remain_rejected(
    product: Product,
    intent: dict,
) -> None:
    anchor = product_variant(product, "anchor", width=2, depth=2, contact_faces=["back"])
    small = product_variant(product, "small", width=0.5, depth=0.5)
    intents = [intent] if intent["id"] == "wall" else [
        {"id": "wall", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        intent,
    ]

    result = solve(make_catalogue(anchor, small), intents)

    assert result.status == "failed"
    assert result.reason == "unsupported-intent"
    assert result.search.attemptedCandidates == 0


@pytest.mark.parametrize(
    "depth,allowed_faces,expected_contacts,forbidden_face",
    [
        (
            1,
            ["back", "left", "right"],
            [("east", "right"), ("north", "back"), ("west", "left")],
            "left",
        ),
        (
            2,
            ["back", "front", "left", "right"],
            [("east", "right"), ("north", "back"), ("south", "front"), ("west", "left")],
            "front",
        ),
    ],
)
def test_object_relative_publishes_and_validates_every_three_or_four_wall_contact(
    product: Product,
    depth: float,
    allowed_faces: list[str],
    expected_contacts: list[tuple[str, str]],
    forbidden_face: str,
) -> None:
    tiny_covering = product_variant(
        product,
        "contact-anchor",
        width=0.2,
        depth=0.2,
        height=0.0005,
        placement_class="floor-covering",
        contact_faces=["back"],
    )
    allowed = product_variant(
        product,
        "allowed-contact-product",
        width=2,
        depth=depth,
        height=0.5,
        contact_faces=allowed_faces,
    )
    forbidden = product_variant(
        product,
        "forbidden-contact-product",
        width=2,
        depth=depth,
        height=0.5,
        contact_faces=["back", "right"],
    )
    contact_room = room_body()
    contact_room["floorPolygon"] = [[-1, -1], [-1, 1], [1, 1], [1, -1]]
    contact_room["walls"] = [
        {"id": name, "label": name, "start": contact_room["floorPolygon"][index], "end": contact_room["floorPolygon"][(index + 1) % 4]}
        for index, name in enumerate(("west", "south", "east", "north"))
    ]
    anchor_intent = {"id": "anchor", "kind": "centred_on", "productId": tiny_covering.id, "wallId": "north"}
    relative_intent = {"id": "relative", "kind": "adjacent_to", "referenceId": "anchor", "side": "front", "gapM": -0.2}

    accepted = solve(
        make_catalogue(tiny_covering, allowed),
        [anchor_intent, {**relative_intent, "productId": allowed.id}],
        room=contact_room,
    )
    rejected = solve(
        make_catalogue(tiny_covering, forbidden),
        [anchor_intent, {**relative_intent, "productId": forbidden.id}],
        room=contact_room,
    )

    assert accepted.status == "solved"
    contacts = accepted.placements[1].wallContacts
    assert [(contact.wallId, contact.face) for contact in contacts] == expected_contacts
    assert accepted.placements[1].wallContact == contacts[0]
    assert rejected.status == "failed"
    assert rejected.reason == "intent-unsatisfiable"
    assert f"{forbidden_face} face" in rejected.detail


def test_floor_covering_overlap_does_not_erase_furniture_access_rules(product: Product) -> None:
    accessible = product_variant(
        product,
        "accessible",
        width=2,
        depth=2,
        contact_faces=["back"],
        access_regions=[{"face": "right", "depthM": 0.6, "required": True, "purpose": "using the bed"}],
    )
    rug = product_variant(product, "rug", width=0.5, depth=0.5, height=0.0005, placement_class="floor-covering")
    blocker = product_variant(product, "blocker", width=0.5, depth=0.5)
    base = [{"id": "anchor", "kind": "centred_on", "productId": accessible.id, "wallId": "north"}]

    rug_result = solve(make_catalogue(accessible, rug), [
        *base,
        {"id": "walkable-rug", "kind": "adjacent_to", "productId": rug.id, "referenceId": "anchor", "side": "right", "gapM": 0.59},
    ])
    touching = solve(make_catalogue(accessible, blocker), [
        *base,
        {"id": "touching", "kind": "adjacent_to", "productId": blocker.id, "referenceId": "anchor", "side": "right", "gapM": 0.6},
    ])
    blocked = solve(make_catalogue(accessible, blocker), [
        *base,
        {"id": "blocked", "kind": "adjacent_to", "productId": blocker.id, "referenceId": "anchor", "side": "right", "gapM": 0.59},
    ])

    assert rug_result.status == "solved"
    assert touching.status == "solved"
    assert blocked.status == "failed"
    assert blocked.reason == "access-region-blocked"


def test_floor_covering_own_required_access_is_enforced_in_both_occupied_orders(product: Product) -> None:
    covering = product_variant(
        product,
        "covering-with-access",
        width=1,
        depth=1,
        height=0.0005,
        placement_class="floor-covering",
        access_regions=[{"face": "right", "depthM": 0.5, "required": True, "purpose": "provider-declared rug access"}],
    )
    furniture = product_variant(product, "floor-standing-obstacle", width=0.5, depth=0.5)
    covering_placement = Placement(instanceId="covering", productId=covering.id, position=(0, 0, 0), yaw=0)
    obstacle_placement = Placement(instanceId="obstacle", productId=furniture.id, position=(0.75, 0, 0), yaw=0)
    room_model = DesignRequest.model_validate({
        "room": room_body(),
        "intents": [{"id": "placeholder", "kind": "centred_on", "productId": furniture.id, "wallId": "north"}],
    }).room

    covering_second = validate_placement(
        covering,
        room_model,
        covering_placement,
        occupied=((furniture, obstacle_placement),),
    )
    furniture_second = validate_placement(
        furniture,
        room_model,
        obstacle_placement,
        occupied=((covering, covering_placement),),
    )

    assert covering_second.status == "invalid-fit"
    assert covering_second.reason == "access-region-blocked"
    assert furniture_second.status == "invalid-fit"
    assert furniture_second.reason == "access-region-blocked"


def test_floor_covering_class_controls_overlap_and_thin_door_exclusion(product: Product) -> None:
    rug = product_variant(product, "thin-rug", width=1, depth=1, height=0.0005, placement_class="floor-covering")
    fake_rug = product_variant(product, "rug-by-name-only", width=1, depth=1, height=0.0005)
    second_rug = product_variant(product, "second-rug", width=1, depth=1, height=0.0005, placement_class="floor-covering")
    room = room_body()
    room["openings"] = [{
        "id": "north-door",
        "kind": "door",
        "wallId": "north",
        "offsetAlongWallM": 0,
        "widthM": 1,
        "bottomM": 0,
        "heightM": 2.1,
        "clearanceDepthM": 0,
        "doorSwing": {"hingeSide": "start"},
    }]
    request = DesignRequest.model_validate({"room": room, "intents": [{"id": "placeholder", "kind": "centred_on", "productId": fake_rug.id, "wallId": "south"}]})
    room_model = request.room
    in_swing = Placement(instanceId="thin-rug", productId=rug.id, position=(0, 0, -4.5), yaw=0)

    door_result = validate_placement(rug, room_model, in_swing)
    occupied = ((rug, Placement(instanceId="rug-a", productId=rug.id, position=(0, 0, 0), yaw=0)),)
    rug_collision = validate_placement(
        second_rug,
        room_model,
        Placement(instanceId="rug-b", productId=second_rug.id, position=(0, 0, 0), yaw=0),
        occupied=occupied,
    )
    ordinary = product_variant(product, "ordinary", width=1, depth=1)
    fake_collision = validate_placement(
        fake_rug,
        room_model,
        Placement(instanceId="fake", productId=fake_rug.id, position=(0, 0, 0), yaw=0),
        occupied=((ordinary, Placement(instanceId="ordinary", productId=ordinary.id, position=(0, 0, 0), yaw=0)),),
    )

    assert door_result.status == "invalid-fit"
    assert door_result.reason == "door-swing-exclusion"
    assert rug_collision.status == "invalid-fit"
    assert rug_collision.reason == "product-collision"
    assert fake_collision.status == "invalid-fit"
    assert fake_collision.reason == "product-collision"


def test_floor_covering_still_enforces_room_and_own_access_containment(product: Product) -> None:
    covering = product_variant(
        product,
        "bounded-covering",
        width=1,
        depth=1,
        height=0.0005,
        placement_class="floor-covering",
        access_regions=[{"face": "right", "depthM": 0.6, "required": True, "purpose": "provider-declared access"}],
    )
    room_model = DesignRequest.model_validate({
        "room": room_body(),
        "intents": [{"id": "placeholder", "kind": "centred_on", "productId": covering.id, "wallId": "north"}],
    }).room

    outside = validate_placement(
        covering,
        room_model,
        Placement(instanceId="outside", productId=covering.id, position=(4.6, 0, 0), yaw=0),
    )
    access_outside = validate_placement(
        covering,
        room_model,
        Placement(instanceId="access-outside", productId=covering.id, position=(4, 0, 0), yaw=0),
    )

    assert outside.status == "invalid-fit"
    assert outside.reason == "footprint-outside-room"
    assert access_outside.status == "invalid-fit"
    assert access_outside.reason == "access-region-outside-room"


def test_object_relative_real_wall_contact_cannot_bypass_face_permissions(product: Product) -> None:
    anchor = product_variant(product, "wall-anchor", width=2, depth=2, contact_faces=["back"])
    flank_without_back_permission = product_variant(product, "unauthorized-flank", width=0.5, depth=0.5)

    result = solve(make_catalogue(anchor, flank_without_back_permission), [
        {"id": "anchor", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        {"id": "left", "kind": "flanking", "productId": flank_without_back_permission.id, "referenceId": "anchor", "side": "left", "gapM": 0.6},
        {"id": "right", "kind": "flanking", "productId": flank_without_back_permission.id, "referenceId": "anchor", "side": "right", "gapM": 0.6},
    ])

    assert result.status == "failed"
    assert result.reason == "intent-unsatisfiable"
    assert "may not contact a wall with its back face" in result.detail


def test_surface_standing_product_cannot_use_floor_relative_path(product: Product) -> None:
    anchor = product_variant(product, "anchor", width=2, depth=2, contact_faces=["back"])
    table_lamp = product_variant(product, "table-lamp", width=0.3, depth=0.3, placement_class="surface-standing")

    result = solve(make_catalogue(anchor, table_lamp), [
        {"id": "anchor", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        {"id": "lamp", "kind": "adjacent_to", "productId": table_lamp.id, "referenceId": "anchor", "side": "right", "gapM": 0.5},
    ])

    assert result.status == "failed"
    assert result.reason == "intent-unsatisfiable"


def test_object_relative_dependency_triggers_bounded_backtracking_of_wall_anchor(product: Product) -> None:
    anchor = product_variant(product, "movable-anchor", width=1, depth=1, contact_faces=["back"])
    relative = product_variant(product, "dependent", width=0.5, depth=0.5)
    narrow = room_body()
    narrow["floorPolygon"] = [[-1.25, -2], [-1.25, 2], [1.25, 2], [1.25, -2]]
    narrow["walls"] = [
        {"id": wall_id, "label": wall_id, "start": narrow["floorPolygon"][index], "end": narrow["floorPolygon"][(index + 1) % 4]}
        for index, wall_id in enumerate(("west", "south", "east", "north"))
    ]
    intents = [
        {"id": "anchor", "kind": "against", "productId": anchor.id, "wallId": "north"},
        {"id": "relative", "kind": "adjacent_to", "productId": relative.id, "referenceId": "anchor", "side": "right", "gapM": 0.6},
    ]

    solved = solve(make_catalogue(anchor, relative), intents, room=narrow, limit=64)
    exhausted = solve(make_catalogue(anchor, relative), intents, room=narrow, limit=2)

    assert solved.status == "solved"
    assert solved.placements[0].position[0] < 0
    assert solved.search.attemptedCandidates > 2
    assert exhausted.status == "failed"
    assert exhausted.reason == "search-exhausted"
    assert exhausted.search.attemptedCandidates == 2
    assert exhausted.search.exhaustive is False


def test_twenty_request_chain_and_tiny_budget_remain_bounded(product: Product) -> None:
    small = product_variant(product, "chain-member", width=0.5, depth=0.5, contact_faces=["back"])
    large_room = room_body()
    large_room["floorPolygon"] = [[-10, -10], [-10, 10], [10, 10], [10, -10]]
    large_room["walls"] = [
        {"id": wall_id, "label": wall_id, "start": large_room["floorPolygon"][index], "end": large_room["floorPolygon"][(index + 1) % 4]}
        for index, wall_id in enumerate(("west", "south", "east", "north"))
    ]
    intents = [{"id": "request-00", "kind": "centred_on", "productId": small.id, "wallId": "north"}]
    intents.extend({
        "id": f"request-{index:02d}",
        "kind": "adjacent_to",
        "productId": small.id,
        "referenceId": f"request-{index - 1:02d}",
        "side": "front",
        "gapM": 0,
    } for index in range(1, 20))

    solved = solve(make_catalogue(small), list(reversed(intents)), room=large_room, limit=20)
    exhausted = solve(make_catalogue(small), list(reversed(intents)), room=large_room, limit=1)

    assert solved.status == "solved"
    assert solved.search.attemptedCandidates == 20
    assert [placement.instanceId for placement in solved.placements] == [intent["id"] for intent in reversed(intents)]
    assert exhausted.status == "failed"
    assert exhausted.reason == "search-exhausted"
    assert exhausted.search.attemptedCandidates == 1


def test_object_relative_derived_centre_crossing_public_bound_is_typed(product: Product) -> None:
    anchor = product_variant(product, "boundary-anchor", width=1, depth=1, contact_faces=["back"])
    relative = product_variant(product, "boundary-relative", width=0.5, depth=0.5)
    bounded_room = room_body()
    bounded_room["floorPolygon"] = [[997, -2], [997, 2], [1000, 2], [1000, -2]]
    bounded_room["walls"] = [
        {"id": wall_id, "label": wall_id, "start": bounded_room["floorPolygon"][index], "end": bounded_room["floorPolygon"][(index + 1) % 4]}
        for index, wall_id in enumerate(("west", "south", "east", "north"))
    ]

    result = solve(make_catalogue(anchor, relative), [
        {"id": "anchor", "kind": "centred_on", "productId": anchor.id, "wallId": "north"},
        {"id": "outside", "kind": "adjacent_to", "productId": relative.id, "referenceId": "anchor", "side": "right", "gapM": 1000},
    ], room=bounded_room, limit=4)

    assert result.status == "failed"
    assert result.reason == "intent-unsatisfiable"
    assert result.failedIntentId == "outside"
    assert result.search.attemptedCandidates == 2
