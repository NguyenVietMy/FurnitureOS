from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

from fastapi.testclient import TestClient
import pytest

from api.catalogue import CatalogueEntry, StaticCatalogue, catalogue
from api.circulation import validate_circulation
from api.design import FEATURED_PRODUCT_ID, resolve_fixture
from api.domain import rectangular_room_shell, validate_placement
from api.main import create_app
from api.models import (
    FixtureSelectionRequest,
    Placement,
    PlacementIntent,
    Product,
    RoomShell,
    SearchReport,
    SolvedDesign,
    SwapRequest,
)
from api.provider import MODEL_ID, ProviderReply, ProviderUsage
from api.swaps import DesignSessionStore, validate_fixed_pose_design


JONATHAN_BED = "bed-rivet-jonathan-queen-walnut"


def _product_variant(base: Product, product_id: str, **updates: object) -> Product:
    value = deepcopy(base.model_dump(mode="json"))
    value.update({"id": product_id, "displayName": product_id, **updates})
    return Product.model_validate(value)


def _source(*products: Product, version: str = "swap-tests-v1") -> StaticCatalogue:
    return StaticCatalogue(version, [
        CatalogueEntry(product=product, private_style_ids=("fixture-style",))
        for product in products
    ])


def _design(
    room: RoomShell,
    products: tuple[Product, ...],
    placements: tuple[Placement, ...],
) -> SolvedDesign:
    intents = tuple(
        PlacementIntent(
            id=placement.instanceId or f"instance-{index}",
            kind="fixture",
            productId=product.id,
        )
        for index, (product, placement) in enumerate(zip(products, placements, strict=True))
    )
    # SolvedDesign needs aligned historical fits. The Swap validator independently
    # recomputes every pair in both directions before admitting or publishing it.
    fits = tuple(
        validate_placement(product, room, placement)
        for product, placement in zip(products, placements, strict=True)
    )
    assert all(fit.status == "fits" for fit in fits)
    return SolvedDesign(
        status="solved",
        room=room,
        intents=intents,
        products=products,
        placements=placements,
        fits=fits,
        search=SearchReport(attemptedCandidates=len(products), candidateLimit=256, exhaustive=True),
    )


def _fixture_design(fixture_id: str = "against-wall") -> SolvedDesign:
    result = resolve_fixture(FixtureSelectionRequest(fixtureId=fixture_id), catalogue)
    assert result.status == "solved"
    return result


def _managed_fixture(client: TestClient, fixture_id: str = "against-wall") -> dict:
    response = client.post("/api/design-resolution", json={"fixtureId": fixture_id, "maxCandidates": 128})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "solved"
    assert body["swap"]["status"] == "available"
    return body


def test_http_swap_changes_one_repeated_instance_and_preserves_every_pose() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    current = _product_variant(base, "repeated-current", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 1}, accessRegions=[], wallContactFaces=[])
    replacement = _product_variant(base, "repeated-replacement", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 1}, accessRegions=[], wallContactFaces=[])
    source = _source(current, replacement)
    store = DesignSessionStore(source, id_factory=lambda: "repeated-session")
    managed = store.register(_design(
        rectangular_room_shell("repeated-room", 6, 6, 3),
        (current, current),
        (
            Placement(instanceId="first", productId=current.id, position=(-1, 0, 0), yaw=0.25),
            Placement(instanceId="second", productId=current.id, position=(1, 0, 0), yaw=-0.25),
        ),
    ), "bedroom")
    client = TestClient(create_app(catalogue_source=source, swap_store=store))
    original = managed.model_dump(mode="json")
    session = original["swap"]
    selected = "first"
    replacement_id = replacement.id

    accepted = client.post("/api/swaps", json={
        "sessionId": session["sessionId"],
        "expectedVersion": 1,
        "instanceId": selected,
        "replacementProductId": replacement_id,
    })
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["version"] == 2
    changed = body["design"]
    assert changed["swap"]["version"] == 2
    assert [placement["position"] for placement in changed["placements"]] == [
        placement["position"] for placement in original["placements"]
    ]
    assert [placement["yaw"] for placement in changed["placements"]] == [
        placement["yaw"] for placement in original["placements"]
    ]
    assert changed["placements"][0]["productId"] == replacement_id
    assert changed["intents"][0]["productId"] == replacement_id
    assert changed["products"][0]["id"] == replacement_id
    assert changed["fits"][0]["placement"] == changed["placements"][0]
    assert changed["placements"][1] == original["placements"][1]
    assert changed["circulation"]["status"] == "clear"


def test_real_candidates_use_the_acceptance_validator_and_reads_do_not_mutate() -> None:
    client = TestClient(create_app())
    original = _managed_fixture(client)
    session = original["swap"]
    instance_id = original["placements"][0]["instanceId"]

    listed = client.get(
        f"/api/swaps/{session['sessionId']}/candidates",
        params={"expectedVersion": 1, "instanceId": instance_id},
    ).json()
    assert listed["status"] == "candidates"
    assert [candidate["product"]["id"] for candidate in listed["candidates"]] == [JONATHAN_BED]
    assert {
        (candidate["product"]["id"], candidate["code"])
        for candidate in listed["rejected"]
    } == {
        ("bed-alkove-hayes-double-wild-oak", "not-touching-declared-wall"),
        ("bed-rivet-york-queen-grey", "not-touching-declared-wall"),
    }
    assert all(candidate["product"]["category"] == "bed" for candidate in listed["rejected"])
    current = client.get(f"/api/swaps/{session['sessionId']}").json()
    assert current["status"] == "current"
    assert current["version"] == 1
    assert current["design"] == original

    accepted = client.post("/api/swaps", json={
        "sessionId": session["sessionId"], "expectedVersion": 1,
        "instanceId": instance_id, "replacementProductId": JONATHAN_BED,
    }).json()
    assert accepted["status"] == "accepted"


def test_unknown_noop_rejection_and_malformed_requests_never_increment() -> None:
    client = TestClient(create_app())
    original = _managed_fixture(client)
    session_id = original["swap"]["sessionId"]
    instance_id = original["placements"][0]["instanceId"]
    current_product_id = original["products"][0]["id"]

    unknown_session = client.get("/api/swaps/not-a-session").json()
    assert unknown_session["status"] == "unknown-session"
    assert client.get(
        f"/api/swaps/{session_id}/candidates",
        params={"expectedVersion": 1, "instanceId": "missing"},
    ).json()["status"] == "unknown-instance"
    assert client.post("/api/swaps", json={
        "sessionId": session_id, "expectedVersion": 1,
        "instanceId": instance_id, "replacementProductId": current_product_id,
    }).json()["status"] == "no-op"
    assert client.post("/api/swaps", json={
        "sessionId": session_id, "expectedVersion": 1,
        "instanceId": instance_id, "replacementProductId": "missing-product",
    }).json()["status"] == "unknown-product"
    incompatible = client.post("/api/swaps", json={
        "sessionId": session_id, "expectedVersion": 1,
        "instanceId": instance_id, "replacementProductId": "rug-rivet-arrow-black-ivory",
    }).json()
    assert incompatible["status"] == "rejected"
    assert incompatible["code"] == "category-incompatible"
    malformed = client.post("/api/swaps", json={
        "sessionId": session_id, "expectedVersion": 1,
        "instanceId": instance_id, "replacementProductId": JONATHAN_BED,
        "products": [], "clearanceWidthM": 0.1, "position": [9, 9, 9],
    })
    assert malformed.status_code == 422
    current = client.get(f"/api/swaps/{session_id}").json()
    assert current["status"] == "current"
    assert current["version"] == 1
    assert current["design"] == original


def test_smaller_products_can_fail_height_and_required_access_with_real_validator() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    room = rectangular_room_shell("small-room", 4, 4, 2.5)
    current = _product_variant(base, "current-bed", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 0.8}, accessRegions=[], wallContactFaces=[])
    too_tall = _product_variant(base, "tall-bed", dimensionsM={"widthM": 0.8, "heightM": 3, "depthM": 0.6}, accessRegions=[], wallContactFaces=[])
    access_outside = _product_variant(
        base,
        "access-bed",
        dimensionsM={"widthM": 0.8, "heightM": 1, "depthM": 0.4},
        accessRegions=[{"face": "front", "depthM": 0.8, "required": True, "purpose": "bed access"}],
        wallContactFaces=[],
    )
    source = _source(current, too_tall, access_outside)
    design = _design(room, (current,), (
        Placement(instanceId="bed", productId=current.id, position=(0, 0, 1.5), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "smaller-invalid-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    client = TestClient(create_app(catalogue_source=source, swap_store=store))

    result = client.get(
        f"/api/swaps/{managed.swap.sessionId}/candidates",
        params={"expectedVersion": 1, "instanceId": "bed"},
    ).json()
    assert result["status"] == "no-compatible-candidates"
    assert {(item["product"]["id"], item["code"]) for item in result["rejected"]} == {
        ("tall-bed", "exceeds-ceiling-height"),
        ("access-bed", "access-region-outside-room"),
    }
    for product_id, reason in (("tall-bed", "exceeds-ceiling-height"), ("access-bed", "access-region-outside-room")):
        rejected = client.post("/api/swaps", json={
            "sessionId": managed.swap.sessionId, "expectedVersion": 1,
            "instanceId": "bed", "replacementProductId": product_id,
        }).json()
        assert rejected["status"] == "rejected"
        assert rejected["code"] == reason
    current = client.get(f"/api/swaps/{managed.swap.sessionId}").json()
    assert current["status"] == "current"
    assert current["version"] == 1
    assert current["design"] == managed.model_dump(mode="json")


def _two_door_room() -> RoomShell:
    value = rectangular_room_shell("circulation-room", 4, 6, 3).model_dump(mode="json")
    value["openings"] = [
        {"id": "north-door", "kind": "door", "wallId": "wall-north", "offsetAlongWallM": 0,
         "widthM": 1, "bottomM": 0, "heightM": 2.1, "clearanceDepthM": 0,
         "doorSwing": {"hingeSide": "start"}},
        {"id": "south-door", "kind": "door", "wallId": "wall-south", "offsetAlongWallM": 0,
         "widthM": 1, "bottomM": 0, "heightM": 2.1, "clearanceDepthM": 0,
         "doorSwing": {"hingeSide": "end"}},
    ]
    return RoomShell.model_validate(value)


def test_locally_valid_replacement_that_blocks_complete_circulation_is_atomic() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    room = _two_door_room()
    wall_slack = 0.01
    initial_width = (4 - 0.601 - 2 * wall_slack) / 2
    current = _product_variant(base, "left-current", dimensionsM={"widthM": initial_width, "heightM": 0.5, "depthM": 0.5}, accessRegions=[], wallContactFaces=[])
    wider = _product_variant(base, "left-wider", dimensionsM={"widthM": initial_width + 0.004, "heightM": 0.5, "depthM": 0.5}, accessRegions=[], wallContactFaces=[])
    right = _product_variant(base, "right-obstacle", dimensionsM={"widthM": initial_width, "heightM": 0.5, "depthM": 0.5}, accessRegions=[], wallContactFaces=[])
    source = _source(current, wider, right)
    design = _design(room, (current, right), (
        Placement(instanceId="left", productId=current.id, position=(-2 + wall_slack + initial_width / 2, 0, 0), yaw=0),
        Placement(instanceId="right", productId=right.id, position=(2 - wall_slack - initial_width / 2, 0, 0), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "circulation-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    client = TestClient(create_app(catalogue_source=source, swap_store=store))

    listed = client.get(
        f"/api/swaps/{managed.swap.sessionId}/candidates",
        params={"expectedVersion": 1, "instanceId": "left"},
    ).json()
    assert listed["status"] == "candidates"
    assert "left-wider" not in [candidate["product"]["id"] for candidate in listed["candidates"]]
    rejected = next(item for item in listed["rejected"] if item["product"]["id"] == "left-wider")
    assert rejected["code"] == "CIRCULATION_BLOCKED"
    result = client.post("/api/swaps", json={
        "sessionId": managed.swap.sessionId, "expectedVersion": 1,
        "instanceId": "left", "replacementProductId": "left-wider",
    }).json()
    assert result["status"] == "rejected"
    assert result["code"] == "CIRCULATION_BLOCKED"
    current_result = client.get(f"/api/swaps/{managed.swap.sessionId}").json()
    assert current_result["status"] == "current"
    assert current_result["version"] == 1
    assert current_result["design"] == managed.model_dump(mode="json")


def test_direct_same_category_room_type_and_placement_class_rejections_are_atomic() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    current = _product_variant(base, "semantic-current", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 1}, accessRegions=[], wallContactFaces=[])
    wrong_class = _product_variant(base, "semantic-covering", dimensionsM={"widthM": 1, "heightM": 0.01, "depthM": 1}, placementClass="floor-covering", accessRegions=[], wallContactFaces=[])
    wrong_room = _product_variant(base, "semantic-living-room", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 1}, roomTypes=["living-room"], accessRegions=[], wallContactFaces=[])
    source = _source(current, wrong_class, wrong_room)
    store = DesignSessionStore(source, id_factory=lambda: "semantic-session")
    managed = store.register(_design(
        rectangular_room_shell("semantic-room", 5, 5, 3),
        (current,),
        (Placement(instanceId="selected", productId=current.id, position=(0, 0, 0), yaw=0),),
    ), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    client = TestClient(create_app(catalogue_source=source, swap_store=store))

    for product_id, code in (
        (wrong_class.id, "placement-class-incompatible"),
        (wrong_room.id, "room-type-incompatible"),
    ):
        result = client.post("/api/swaps", json={
            "sessionId": managed.swap.sessionId, "expectedVersion": 1,
            "instanceId": "selected", "replacementProductId": product_id,
        }).json()
        assert result["status"] == "rejected"
        assert result["code"] == code
    current_result = client.get(f"/api/swaps/{managed.swap.sessionId}").json()
    assert current_result["version"] == 1
    assert current_result["design"] == managed.model_dump(mode="json")


def test_existing_clearance_above_minimum_is_preserved_through_acceptance() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    current = _product_variant(base, "wide-clearance-current", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 1}, accessRegions=[], wallContactFaces=[])
    replacement = _product_variant(base, "wide-clearance-replacement", dimensionsM={"widthM": 0.9, "heightM": 1, "depthM": 0.9}, accessRegions=[], wallContactFaces=[])
    source = _source(current, replacement)
    design = _design(
        rectangular_room_shell("wide-clearance-room", 6, 6, 3),
        (current,),
        (Placement(instanceId="selected", productId=current.id, position=(0, 0, 0), yaw=0),),
    )
    circulation = validate_circulation(design, 0.80)
    assert circulation.status == "clear"
    design = design.model_copy(update={"circulation": circulation}, deep=True)
    store = DesignSessionStore(source, id_factory=lambda: "wide-clearance-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    assert managed.swap.clearanceWidthM == 0.80
    accepted = store.swap(SwapRequest(
        sessionId=managed.swap.sessionId,
        expectedVersion=1,
        instanceId="selected",
        replacementProductId=replacement.id,
    ))
    assert accepted.status == "accepted"
    assert accepted.design.circulation is not None
    assert accepted.design.circulation.clearanceWidthM == 0.80
    assert accepted.design.swap is not None and accepted.design.swap.clearanceWidthM == 0.80


def test_real_unsupported_circulation_limit_refuses_session() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    product = _product_variant(base, "large-room-product", dimensionsM={"widthM": 1, "heightM": 1, "depthM": 1}, accessRegions=[], wallContactFaces=[])
    source = _source(product)
    design = _design(
        rectangular_room_shell("unsupported-circulation-room", 40, 40, 3),
        (product,),
        (Placement(instanceId="selected", productId=product.id, position=(0, 0, 0), yaw=0),),
    )
    direct = validate_circulation(design, 0.60)
    assert direct.status == "CIRCULATION_UNSUPPORTED"
    store = DesignSessionStore(source, id_factory=lambda: "unsupported-must-not-exist")
    refused = store.register(design, "bedroom")
    assert refused.swap is not None and refused.swap.status == "unavailable"
    assert "circulation lattice" in refused.swap.detail
    assert store.session_count() == 0


def test_fixed_pose_validator_enforces_every_floor_covering_overlap_direction() -> None:
    base = catalogue.get(FEATURED_PRODUCT_ID)
    assert base is not None
    room = rectangular_room_shell("covering-room", 6, 6, 3)
    standing = _product_variant(base, "standing", dimensionsM={"widthM": 1, "heightM": 0.5, "depthM": 1}, accessRegions=[], wallContactFaces=[])
    covering = _product_variant(base, "covering", dimensionsM={"widthM": 2, "heightM": 0.01, "depthM": 2}, placementClass="floor-covering", accessRegions=[], wallContactFaces=[])
    source = _source(standing, covering)
    allowed = _design(room, (standing, covering), (
        Placement(instanceId="standing", productId=standing.id, position=(0, 0, 0), yaw=0),
        Placement(instanceId="covering", productId=covering.id, position=(0, 0, 0), yaw=0),
    ))
    validated, failure = validate_fixed_pose_design(source, allowed, 0.6)
    assert failure is None
    assert validated is not None

    second_covering = _product_variant(base, "second-covering", dimensionsM={"widthM": 1, "heightM": 0.01, "depthM": 1}, placementClass="floor-covering", accessRegions=[], wallContactFaces=[])
    covering_collision = _design(room, (covering, second_covering), (
        Placement(instanceId="covering", productId=covering.id, position=(0, 0, 0), yaw=0),
        Placement(instanceId="second", productId=second_covering.id, position=(0, 0, 0), yaw=0),
    ))
    _, collision_failure = validate_fixed_pose_design(_source(covering, second_covering), covering_collision, 0.6)
    assert collision_failure is not None and collision_failure.code == "product-collision"

    access_covering = _product_variant(
        base,
        "access-covering",
        dimensionsM={"widthM": 1, "heightM": 0.01, "depthM": 1},
        placementClass="floor-covering",
        accessRegions=[{"face": "front", "depthM": 1, "required": True, "purpose": "covering access"}],
        wallContactFaces=[],
    )
    access_blocked = _design(room, (access_covering, standing), (
        Placement(instanceId="access-covering", productId=access_covering.id, position=(0, 0, 0), yaw=0),
        Placement(instanceId="standing", productId=standing.id, position=(0, 0, 1), yaw=0),
    ))
    _, access_failure = validate_fixed_pose_design(_source(access_covering, standing), access_blocked, 0.6)
    assert access_failure is not None and access_failure.code == "access-region-blocked"


def test_simultaneous_http_swaps_have_one_winner_and_replay_is_stale() -> None:
    application = create_app()
    setup_client = TestClient(application)
    original = _managed_fixture(setup_client)
    session_id = original["swap"]["sessionId"]
    instance_id = original["placements"][0]["instanceId"]
    payload = {
        "sessionId": session_id, "expectedVersion": 1,
        "instanceId": instance_id, "replacementProductId": JONATHAN_BED,
    }

    def submit() -> dict:
        with TestClient(application) as client:
            return client.post("/api/swaps", json=payload).json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (executor.submit(submit), executor.submit(submit))]
    assert sorted(outcome["status"] for outcome in outcomes) == ["accepted", "stale-version"]
    replay = setup_client.post("/api/swaps", json=payload).json()
    assert replay["status"] == "stale-version"
    assert replay["currentVersion"] == 2


def test_expiration_separate_process_and_catalogue_change_fail_closed() -> None:
    clock = [0.0]
    source = catalogue
    store = DesignSessionStore(source, ttl_seconds=5, clock=lambda: clock[0], id_factory=lambda: "expiring")
    managed = store.register(_fixture_design(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    clock[0] = 6
    expired = store.current(managed.swap.sessionId)
    assert expired.status == "expired-session"
    assert store.current(managed.swap.sessionId).status == "unknown-session"
    assert managed.swap.version == 1

    app_one = TestClient(create_app())
    first = _managed_fixture(app_one)
    app_two = TestClient(create_app())
    assert app_two.get(f"/api/swaps/{first['swap']['sessionId']}").json()["status"] == "unknown-session"

    class MutableCatalogue:
        def __init__(self) -> None:
            self.version = catalogue.version

        def list(self, query=None):
            return catalogue.list(query)

        def get(self, product_id: str):
            return catalogue.get(product_id)

        def private_style_ids(self, product_id: str):
            return catalogue.private_style_ids(product_id)

    mutable = MutableCatalogue()
    changed_client = TestClient(create_app(catalogue_source=mutable))
    changed_design = _managed_fixture(changed_client)
    mutable.version = "catalogue-v2"
    changed = changed_client.get(f"/api/swaps/{changed_design['swap']['sessionId']}").json()
    assert changed["status"] == "catalogue-changed"
    assert changed_client.get(f"/api/swaps/{changed_design['swap']['sessionId']}").json()["status"] == "unknown-session"


def test_capacity_waits_for_mutation_lock_and_never_evicts_live_session() -> None:
    entered = Event()
    release = Event()
    calls = [0]

    def blocking_validator(source, design, clearance):
        calls[0] += 1
        if calls[0] == 2:
            entered.set()
            assert release.wait(5)
        return validate_fixed_pose_design(source, design, clearance)

    store = DesignSessionStore(
        catalogue,
        capacity=1,
        validator=blocking_validator,
        id_factory=lambda: "capacity-session",
    )
    managed = store.register(_fixture_design(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    request = SwapRequest(
        sessionId=managed.swap.sessionId,
        expectedVersion=1,
        instanceId=managed.placements[0].instanceId,
        replacementProductId=JONATHAN_BED,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(store.swap, request)
        assert entered.wait(5)
        registration = executor.submit(store.register, _fixture_design(), "bedroom")
        assert not registration.done()
        release.set()
        assert mutation.result().status == "accepted"
        refused = registration.result()
    assert refused.swap is not None and refused.swap.status == "unavailable"
    assert "capacity" in refused.swap.detail
    assert store.session_count() == 1
    assert store.current(managed.swap.sessionId).status == "current"


def test_clock_advance_during_validation_cannot_publish_or_increment() -> None:
    clock = [0.0]
    calls = [0]

    def advancing_validator(source, design, clearance):
        calls[0] += 1
        result = validate_fixed_pose_design(source, design, clearance)
        if calls[0] == 2:
            clock[0] = 11
        return result

    store = DesignSessionStore(
        catalogue,
        ttl_seconds=10,
        clock=lambda: clock[0],
        validator=advancing_validator,
        id_factory=lambda: "clock-session",
    )
    managed = store.register(_fixture_design(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    result = store.swap(SwapRequest(
        sessionId=managed.swap.sessionId,
        expectedVersion=1,
        instanceId=managed.placements[0].instanceId,
        replacementProductId=JONATHAN_BED,
    ))
    assert result.status == "expired-session"
    assert managed.swap.version == 1
    assert store.session_count() == 0


def test_invalid_initial_design_cannot_create_a_session() -> None:
    design = _fixture_design()
    raised = design.placements[0].model_copy(update={"position": (0, 1, design.placements[0].position[2])})
    invalid = design.model_copy(update={"placements": (raised,)}, deep=True)
    store = DesignSessionStore(catalogue, id_factory=lambda: "must-not-exist")
    refused = store.register(invalid, "bedroom")
    assert refused.swap is not None and refused.swap.status == "unavailable"
    assert "floor-centre" in refused.swap.detail
    assert store.session_count() == 0


def test_live_http_success_registers_real_generation_without_a_paid_call(monkeypatch) -> None:
    class ControlledProvider:
        def generate(self, **_kwargs):
            return ProviderReply(
                payload={"intents": [{
                    "id": "anchor-bed", "kind": "against", "productId": FEATURED_PRODUCT_ID,
                    "wallId": "wall-north", "face": "back",
                }]},
                model=MODEL_ID,
                stop_reason="end_turn",
                usage=ProviderUsage(inputTokens=100, outputTokens=25, costUsd=0.001125),
                latency_ms=3,
            )

    monkeypatch.setenv("FURNITUREOS_LIVE_GENERATION_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "controlled-not-sent")
    monkeypatch.setenv("FURNITUREOS_WORKSPACE_ID", "controlled-workspace")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "controlled-workspace")
    monkeypatch.setenv("FURNITUREOS_GENERATION_SPEND_CAP_USD", "5")
    client = TestClient(create_app(generation_provider=ControlledProvider()))
    result = client.post("/api/live-bedroom/generate", json={
        "roomType": "bedroom", "referenceId": "ref-01",
    })
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "solved"
    assert body["design"]["swap"]["status"] == "available"
    session_id = body["design"]["swap"]["sessionId"]
    assert client.get(f"/api/swaps/{session_id}").json()["status"] == "current"
