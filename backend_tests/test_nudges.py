from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from heapq import nsmallest
import json
from math import hypot
import sys
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest

from api.catalogue import catalogue
from api.circulation import validate_circulation_with_witness
from api.design import resolve_fixture
from api.domain import validate_placement
from api.main import create_app
from api.models import FixtureSelectionRequest, NudgeRequest, SolvedDesign, SwapRequest
from api.models import Placement
from api.domain import _polygons_overlap, rectangular_room_shell
from api.nudges import (
    CLIENT_MEMBERSHIP_MARGIN_M,
    HalfPlane,
    NudgeCertificate,
    NudgeProofError,
    _best_separator,
    _common_endpoint_separator,
    _choose_attachment,
    build_nudge_certificate,
    certificate_contains,
    nudged_placement,
)
from api.swaps import DesignSessionStore, validate_fixed_pose_design
from backend_tests.test_swaps import _design, _product_variant, _source, _two_door_room


JONATHAN_BED = "bed-rivet-jonathan-queen-walnut"


def _fixture(fixture_id: str = "against-wall") -> SolvedDesign:
    result = resolve_fixture(FixtureSelectionRequest(fixtureId=fixture_id), catalogue)
    assert result.status == "solved"
    return result


def _managed(client: TestClient, fixture_id: str = "against-wall") -> dict:
    response = client.post("/api/design-resolution", json={"fixtureId": fixture_id, "maxCandidates": 128})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "solved"
    assert body["swap"]["status"] == "available"
    return body


def _region(client: TestClient, design: dict, instance_id: str | None = None) -> dict:
    session = design["swap"]
    selected = instance_id or design["placements"][0]["instanceId"]
    response = client.get(
        f"/api/nudges/{session['sessionId']}/region",
        params={"expectedVersion": session["version"], "instanceId": selected},
    )
    assert response.status_code == 200
    return response.json()


def _inside(region: dict, point: list[float]) -> bool:
    displacement = [point[0] - region["origin"][0], point[1] - region["origin"][1]]
    return all(
        plane["normal"][0] * displacement[0] + plane["normal"][1] * displacement[1]
        <= plane["maxDisplacementM"] - CLIENT_MEMBERSHIP_MARGIN_M + 1e-12
        for plane in region["constraints"]
    )


def test_real_bed_region_is_convex_useful_and_every_sample_revalidates() -> None:
    design = _fixture()
    store = DesignSessionStore(catalogue, id_factory=lambda: "bed-nudge", region_id_factory=lambda: "bed-region")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    region = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert region.status == "available"
    assert region.origin == (-0.5, -0.383505)
    assert len(region.polygon) >= 3
    assert all(abs(hypot(*plane.normal) - 1) < 1e-12 for plane in region.constraints)
    assert max(point[1] for point in region.polygon) >= 0.05
    assert min(point[0] for point in region.polygon) <= -0.05
    assert max(point[0] for point in region.polygon) >= 0.05

    original_intents = managed.intents
    selected = managed.placements[0]
    for displacement in (*region.polygon, (0.0, 0.05), (0.025, 0.025)):
        # Stay strictly within the client subset when sampling polygon corners.
        target = (
            region.origin[0] + displacement[0] * 0.99,
            region.origin[1] + displacement[1] * 0.99,
        )
        placements = list(managed.placements)
        placements[0] = nudged_placement(managed.products[0], managed.room, selected, target)
        provisional = managed.model_copy(update={"placements": tuple(placements)}, deep=True)
        validated, failure = validate_fixed_pose_design(catalogue, provisional, managed.swap.clearanceWidthM)
        assert failure is None
        assert validated is not None and validated.circulation is not None
        assert validated.circulation.status == "clear"
        assert validated.intents == original_intents


def test_http_nudge_detaches_wall_contact_preserves_provenance_and_increments_shared_version() -> None:
    client = TestClient(create_app())
    original = _managed(client)
    region = _region(client, original)
    target = [region["origin"][0], region["origin"][1] + 0.05]
    response = client.post("/api/nudges", json={
        "sessionId": original["swap"]["sessionId"],
        "expectedVersion": 1,
        "instanceId": original["placements"][0]["instanceId"],
        "regionId": region["regionId"],
        "target": target,
    })
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "accepted"
    assert result["version"] == 2 == result["design"]["swap"]["version"]
    moved = result["design"]["placements"][0]
    assert moved["position"] == [target[0], original["placements"][0]["position"][1], target[1]]
    assert moved["yaw"] == original["placements"][0]["yaw"]
    assert moved["wallContact"] is None and moved["wallContacts"] == []
    assert result["design"]["intents"] == original["intents"]
    assert result["design"]["circulation"]["status"] == "clear"
    assert client.post("/api/nudges", json={
        "sessionId": original["swap"]["sessionId"], "expectedVersion": 1,
        "instanceId": original["placements"][0]["instanceId"],
        "regionId": region["regionId"], "target": target,
    }).json()["status"] == "stale-version"


def test_rug_region_permits_meaningful_motion_across_a_standing_product() -> None:
    client = TestClient(create_app())
    original = _managed(client, "rug-under-bed")
    rug_index = next(index for index, product in enumerate(original["products"]) if product["placementClass"] == "floor-covering")
    rug = original["placements"][rug_index]
    region = _region(client, original, rug["instanceId"])
    assert region["status"] == "available"
    target = [region["origin"][0] + 0.20, region["origin"][1]]
    assert _inside(region, target)
    result = client.post("/api/nudges", json={
        "sessionId": original["swap"]["sessionId"], "expectedVersion": 1,
        "instanceId": rug["instanceId"], "regionId": region["regionId"], "target": target,
    }).json()
    assert result["status"] == "accepted"
    assert result["design"]["placements"][rug_index]["position"][0] == pytest.approx(target[0])
    assert result["design"]["placements"][0] == original["placements"][0]


def test_outside_noop_old_replaced_and_failed_region_requests_are_atomic(monkeypatch) -> None:
    store = DesignSessionStore(catalogue, id_factory=lambda: "certificate-session")
    managed = store.register(_fixture(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    first = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert first.status == "available"
    outside = store.nudge(NudgeRequest(
        sessionId=managed.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        regionId=first.regionId, target=(first.origin[0] + 1, first.origin[1] + 1),
    ))
    assert outside.status == "rejected" and outside.code == "outside-certified-region"
    noop = store.nudge(NudgeRequest(
        sessionId=managed.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        regionId=first.regionId, target=first.origin,
    ))
    assert noop.status == "rejected" and noop.code == "no-op"

    second = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert second.status == "available" and second.regionId != first.regionId
    old = store.nudge(NudgeRequest(
        sessionId=managed.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        regionId=first.regionId, target=(first.origin[0], first.origin[1] + 0.03),
    ))
    assert old.status == "certificate-missing"

    def fail(*_args, **_kwargs):
        raise NudgeProofError("controlled certificate failure")

    monkeypatch.setattr("api.swaps.build_nudge_certificate", fail)
    failed = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert failed.status == "unavailable"
    accepted = store.nudge(NudgeRequest(
        sessionId=managed.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        regionId=second.regionId, target=(second.origin[0], second.origin[1] + 0.03),
    ))
    assert accepted.status == "accepted"
    assert store.certificate_count() == 0


def test_certificate_expiry_and_swap_invalidation_fail_closed() -> None:
    clock = [0.0]
    store = DesignSessionStore(
        catalogue,
        clock=lambda: clock[0],
        ttl_seconds=300,
        id_factory=lambda: "expiring-nudge",
        region_id_factory=lambda: "expiring-region",
    )
    managed = store.register(_fixture(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    region = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert region.status == "available" and region.expiresInMs == 120_000
    clock[0] = 121
    expired = store.nudge(NudgeRequest(
        sessionId=managed.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        regionId=region.regionId, target=(region.origin[0], region.origin[1] + 0.03),
    ))
    assert expired.status == "certificate-missing"

    fresh = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert fresh.status == "available"
    swapped = store.swap(SwapRequest(
        sessionId=managed.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        replacementProductId=JONATHAN_BED,
    ))
    assert swapped.status == "accepted"
    assert store.certificate_count() == 0
    assert store.nudge(NudgeRequest(
        sessionId=managed.swap.sessionId, expectedVersion=2, instanceId="bed-against-north",
        regionId=fresh.regionId, target=(fresh.origin[0], fresh.origin[1] + 0.03),
    )).status == "certificate-missing"


def test_same_version_nudge_nudge_and_swap_nudge_races_have_one_winner() -> None:
    def nudge_payload(client: TestClient, design: dict) -> dict:
        region = _region(client, design)
        return {
            "sessionId": design["swap"]["sessionId"], "expectedVersion": 1,
            "instanceId": design["placements"][0]["instanceId"], "regionId": region["regionId"],
            "target": [region["origin"][0], region["origin"][1] + 0.03],
        }

    application = create_app()
    setup = TestClient(application)
    original = _managed(setup)
    payload = nudge_payload(setup, original)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (
            executor.submit(lambda: TestClient(application).post("/api/nudges", json=payload).json()),
            executor.submit(lambda: TestClient(application).post("/api/nudges", json=payload).json()),
        )]
    assert sorted(value["status"] for value in outcomes) == ["accepted", "stale-version"]

    application = create_app()
    setup = TestClient(application)
    original = _managed(setup)
    payload = nudge_payload(setup, original)
    swap_payload = {
        "sessionId": original["swap"]["sessionId"], "expectedVersion": 1,
        "instanceId": original["placements"][0]["instanceId"], "replacementProductId": JONATHAN_BED,
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (
            executor.submit(lambda: TestClient(application).post("/api/nudges", json=payload).json()),
            executor.submit(lambda: TestClient(application).post("/api/swaps", json=swap_payload).json()),
        )]
    assert sorted(value["status"] for value in outcomes) == ["accepted", "stale-version"]


def test_blocking_nudge_validation_does_not_block_other_sessions() -> None:
    entered = Event()
    release = Event()
    calls = [0]

    def blocking_validator(source, design, clearance):
        calls[0] += 1
        if calls[0] == 3:
            entered.set()
            assert release.wait(5)
        return validate_fixed_pose_design(source, design, clearance)

    ids = iter(("first-session", "second-session", "third-session"))
    store = DesignSessionStore(catalogue, capacity=3, validator=blocking_validator, id_factory=lambda: next(ids))
    first = store.register(_fixture(), "bedroom")
    second = store.register(_fixture(), "bedroom")
    assert first.swap is not None and first.swap.status == "available"
    assert second.swap is not None and second.swap.status == "available"
    region = store.nudge_region(first.swap.sessionId, 1, "bed-against-north")
    assert region.status == "available"
    request = NudgeRequest(
        sessionId=first.swap.sessionId, expectedVersion=1, instanceId="bed-against-north",
        regionId=region.regionId, target=(region.origin[0], region.origin[1] + 0.03),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(store.nudge, request)
        assert entered.wait(5)
        assert store.current(second.swap.sessionId).status == "current"
        second_region = store.nudge_region(second.swap.sessionId, 1, "bed-against-north")
        assert second_region.status == "available"
        third = store.register(_fixture(), "bedroom")
        assert third.swap is not None and third.swap.status == "available"
        release.set()
        assert mutation.result().status == "accepted"


def test_numeric_certificate_margin_and_json_round_trip_fail_closed() -> None:
    certificate = NudgeCertificate(
        region_id="r", session_id="s", version=1, instance_id="i", origin=(999.0, -999.0),
        fixed_y=0, fixed_yaw=0,
        half_planes=(HalfPlane((1.0, 0.0), 0.0009999, "placement touch"),),
        polygon=((0.0, 0.0), (0.0009, 0.0), (0.0, 0.0001)), expires_at=1,
    )
    encoded_target = json.loads(json.dumps([999.000999898, -999.0]))
    assert certificate_contains(certificate, tuple(encoded_target))
    assert not certificate_contains(certificate, (999.0009998995, -999.0))
    assert not certificate_contains(certificate, (999.0009999, -999.0))

    moving = ((999.0, 999.0), (1000.0, 999.0), (1000.0, 1000.0), (999.0, 1000.0))
    fixed = ((1000.0, 999.0), (1001.0, 999.0), (1001.0, 1000.0), (1000.0, 1000.0))
    placement_plane = _best_separator(moving, fixed, 0.001, "placement")
    assert placement_plane.maximum == pytest.approx(0.001 - 1e-7)
    with pytest.raises(NudgeProofError):
        _best_separator(moving, fixed, 1e-9, "circulation touch")


def test_malformed_and_unknown_http_requests_are_typed_or_rejected() -> None:
    client = TestClient(create_app())
    original = _managed(client)
    assert client.get(
        "/api/nudges/missing/region", params={"expectedVersion": 1, "instanceId": "missing"},
    ).json()["status"] == "unknown-session"
    malformed = client.post(
        "/api/nudges",
        content=(
            '{"sessionId":"' + original["swap"]["sessionId"]
            + '","expectedVersion":1,"instanceId":"' + original["placements"][0]["instanceId"]
            + '","regionId":"x","target":["NaN",0]}'
        ),
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 422


def _small_product(product_id: str, width=0.4, depth=0.4, **updates):
    base = catalogue.get("bed-prudence-tufted-queen-natural")
    assert base is not None
    values = {"dimensionsM": {"widthM": width, "heightM": 0.3, "depthM": depth},
        "accessRegions": [], "wallContactFaces": [], **updates}
    return _product_variant(base, product_id, **values)


def test_actual_large_lattice_never_retains_more_than_32_attachment_candidates() -> None:
    selected = _small_product("large-lattice-selected", width=0.2, depth=0.2,
        accessRegions=[{"face": "right", "depthM": 0.6, "required": True, "purpose": "entry"}])
    placement = Placement(instanceId="selected", productId=selected.id, position=(-4, 0, 0), yaw=0)
    design = _design(rectangular_room_shell("large-lattice-room", 10, 12, 3), (selected,), (placement,))
    circulation, witness = validate_circulation_with_witness(design, 0.6)
    assert circulation.status == "clear" and witness is not None
    assert len(witness.grid) > 40_000
    allowed = frozenset(key for key, _parent in witness.parents)
    target = witness.accesses[0].target
    footprint = ((-4.1, -0.1), (-3.9, -0.1), (-3.9, 0.1), (-4.1, 0.1))
    # Independent bounded heap reference for the specified old full-sort order.
    # The worked pose's right-face headroom is x - 0.3 - (-3.9) + 1e-9.
    expected = tuple(nsmallest(32, (
        (-min(point[0] + 3.6 + 1e-9, 0.25), hypot(point[0] - target[0], point[1] - target[1]), key, point)
        for key, point in witness.grid
        if key in allowed and point[0] + 3.6 + 1e-9 >= 0.05 + 1e-7
    )))
    assert expected[0][3] == (-3.35, 0.0)

    # Observe the live retained list at every allocator line, including before
    # an eject/pop. This catches an append-33-then-truncate implementation, not
    # just a bound on the number of eventual geometric proof attempts.
    target_code = _choose_attachment.__code__
    for grid in (witness.grid, tuple(reversed(witness.grid))):
        maximum_retained = 0
        retained = ()
        def observe(frame, event, _arg):
            nonlocal maximum_retained, retained
            if frame.f_code is not target_code:
                return None
            ranked = frame.f_locals.get("ranked", ())
            maximum_retained = max(maximum_retained, len(ranked))
            assert maximum_retained <= 32, f"Retained {maximum_retained} attachment candidates on actual large lattice."
            if event == "return":
                retained = tuple(ranked)
            return observe

        prior_trace = sys.gettrace()
        try:
            sys.settrace(observe)
            key, point, constraints = _choose_attachment(
                target, (1.0, 0.0), footprint, replace(witness, grid=grid), allowed,
                "selected", time.monotonic() + 20,
            )
        finally:
            sys.settrace(prior_trace)
        assert maximum_retained == 32
        assert retained == expected
        assert key == expected[0][2] and point == expected[0][3]
        assert constraints


def test_thin_obstacle_cannot_be_crossed_even_when_both_endpoints_are_valid() -> None:
    selected = _small_product("selected", width=0.2, depth=0.2)
    thin = _small_product("thin", width=0.002, depth=2.5)
    source = _source(selected, thin)
    design = _design(rectangular_room_shell("thin-room", 4, 4, 3), (selected, thin), (
        Placement(instanceId="selected", productId=selected.id, position=(-0.5, 0, 0), yaw=0),
        Placement(instanceId="thin", productId=thin.id, position=(0, 0, 0), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "thin-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    # Endpoint on the opposite side is independently locally and globally valid.
    other_side = managed.model_copy(update={"placements": (
        managed.placements[0].model_copy(update={"position": (0.5, 0, 0)}), managed.placements[1],
    )}, deep=True)
    assert validate_fixed_pose_design(source, other_side, 0.6)[0] is not None
    region = store.nudge_region(managed.swap.sessionId, 1, "selected")
    assert region.status == "available"
    assert max(point[0] for point in region.polygon) < 0.401
    assert store.nudge(NudgeRequest(sessionId=managed.swap.sessionId, expectedVersion=1,
        instanceId="selected", regionId=region.regionId, target=(0.5, 0))).status == "rejected"
    # The complete interpolated translation encounters the thin obstacle.
    middle = other_side.model_copy(update={"placements": (
        other_side.placements[0].model_copy(update={"position": (0, 0, 0)}), other_side.placements[1],
    )}, deep=True)
    assert validate_fixed_pose_design(source, middle, 0.6)[1].code == "product-collision"


def test_preserved_two_door_witness_clamps_before_a_locally_valid_route_blocker() -> None:
    left = _small_product("route-left", width=1.55, depth=0.5)
    right = _small_product("route-right", width=1.55, depth=0.5)
    source = _source(left, right)
    design = _design(_two_door_room(), (left, right), (
        Placement(instanceId="left", productId=left.id, position=(-1.215, 0, 0), yaw=0),
        Placement(instanceId="right", productId=right.id, position=(1.215, 0, 0), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "route-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    region = store.nudge_region(managed.swap.sessionId, 1, "left")
    assert region.status == "available"
    blocked = managed.placements[0].model_copy(update={"position": (-0.865, 0, 0)})
    assert validate_placement(left, design.room, blocked, occupied=((right, managed.placements[1]),)).status == "fits"
    blocked_design = managed.model_copy(update={"placements": (blocked, managed.placements[1])}, deep=True)
    assert validate_fixed_pose_design(source, blocked_design, 0.6)[1].code == "CIRCULATION_BLOCKED"
    assert max(point[0] for point in region.polygon) < 0.28
    assert store.nudge(NudgeRequest(sessionId=managed.swap.sessionId, expectedVersion=1,
        instanceId="left", regionId=region.regionId, target=(-0.865, 0))).status == "rejected"


def test_a_tether_cannot_use_different_sides_of_one_obstacle() -> None:
    moving = ((-2, -0.3), (-1.4, -0.3), (-1.4, 0.3), (-2, 0.3))
    fixed = ((1.4, -0.3), (2, -0.3), (2, 0.3), (1.4, 0.3))
    obstacle = ((-0.01, -1), (0.01, -1), (0.01, 1), (-0.01, 1))
    assert not _polygons_overlap(moving, obstacle, 1e-9)
    assert not _polygons_overlap(fixed, obstacle, 1e-9)
    with pytest.raises(NudgeProofError):
        _common_endpoint_separator(moving, fixed, obstacle, 1e-9, "thin tether blocker")


@pytest.mark.parametrize("slack", [0.001, 1e-9])
def test_owning_sat_touch_arithmetic_immediately_inside_on_and_outside(slack) -> None:
    square = ((-1, 0), (0, 0), (0, 1), (-1, 1))
    def other(overlap):
        return ((-overlap, 0), (1 - overlap, 0), (1 - overlap, 1), (-overlap, 1))
    epsilon = slack * 0.01
    assert not _polygons_overlap(square, other(slack - epsilon), slack)
    # Put the selected edge at zero so the tested projection overlap is exactly
    # the stored tolerance, not a rounded 1 - (1 - slack) construction.
    assert not _polygons_overlap(square, other(slack), slack)
    assert not _polygons_overlap(square, other(0), slack)
    assert _polygons_overlap(square, other(slack + epsilon), slack)


def test_timeout_budget_reissue_token_and_expiry_cannot_publish_partial_certificates(monkeypatch) -> None:
    store = DesignSessionStore(catalogue, id_factory=lambda: "budget-session")
    managed = store.register(_fixture(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    monkeypatch.setattr("api.nudges.REGION_DEADLINE_SECONDS", -1)
    timed_out = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert timed_out.status == "unavailable" and "timed out" in timed_out.detail
    assert store.certificate_count() == 0
    monkeypatch.setattr("api.nudges.REGION_DEADLINE_SECONDS", 2)
    monkeypatch.setattr("api.nudges.MAX_HALF_PLANES", 4)
    budget = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert budget.status == "unavailable" and "budget" in budget.detail
    monkeypatch.setattr("api.nudges.MAX_HALF_PLANES", 4096)

    entered, release = Event(), Event()
    calls = [0]
    original_builder = build_nudge_certificate
    def held_builder(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            entered.set()
            assert release.wait(5)
        return original_builder(*args, **kwargs)
    monkeypatch.setattr("api.swaps.build_nudge_certificate", held_builder)
    with ThreadPoolExecutor(max_workers=2) as executor:
        old = executor.submit(store.nudge_region, managed.swap.sessionId, 1, "bed-against-north")
        assert entered.wait(5)
        latest = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
        assert latest.status == "available"
        release.set()
        assert old.result().status == "unavailable"
    assert store.certificate_count() == 1


def test_certificate_capacity_and_session_expiry_remove_all_owned_certificates() -> None:
    clock = [0.0]
    ids = iter(("capacity-one", "capacity-two"))
    store = DesignSessionStore(catalogue, capacity=2, ttl_seconds=5, clock=lambda: clock[0], id_factory=lambda: next(ids))
    first, second = store.register(_fixture(), "bedroom"), store.register(_fixture(), "bedroom")
    for design in (first, second):
        assert design.swap is not None and design.swap.status == "available"
        assert store.nudge_region(design.swap.sessionId, 1, "bed-against-north").status == "available"
    assert store.certificate_count() == 2
    refused = store.register(_fixture(), "bedroom")
    assert refused.swap.status == "unavailable"
    assert store.certificate_count() == 2
    clock[0] = 6
    assert store.certificate_count() == 0 and store.session_count() == 0


def test_version_change_during_region_compute_cannot_publish(monkeypatch) -> None:
    store = DesignSessionStore(catalogue, id_factory=lambda: "stale-region")
    managed = store.register(_fixture(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    entered, release = Event(), Event()
    def held_builder(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return build_nudge_certificate(*args, **kwargs)
    monkeypatch.setattr("api.swaps.build_nudge_certificate", held_builder)
    with ThreadPoolExecutor(max_workers=2) as executor:
        region = executor.submit(store.nudge_region, managed.swap.sessionId, 1, "bed-against-north")
        assert entered.wait(5)
        assert store.swap(SwapRequest(sessionId=managed.swap.sessionId, expectedVersion=1,
            instanceId="bed-against-north", replacementProductId=JONATHAN_BED)).status == "accepted"
        release.set()
        assert region.result().status == "stale-version"
    assert store.certificate_count() == 0


def test_required_access_is_protected_in_both_moving_directions() -> None:
    access_product = _small_product("access-owner", width=0.4, depth=0.4,
        accessRegions=[{"face": "front", "depthM": 0.8, "required": True, "purpose": "opening drawers"}])
    solid = _small_product("solid")
    source = _source(access_product, solid)
    design = _design(rectangular_room_shell("access-room", 5, 5, 3), (access_product, solid), (
        Placement(instanceId="owner", productId=access_product.id, position=(0, 0, 0), yaw=0),
        Placement(instanceId="solid", productId=solid.id, position=(0, 0, 1.6), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "access-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    for instance_id, target in (("solid", (0, 0.8)), ("owner", (0, 0.8))):
        region = store.nudge_region(managed.swap.sessionId, 1, instance_id)
        assert region.status == "available", region.detail
        assert store.nudge(NudgeRequest(sessionId=managed.swap.sessionId, expectedVersion=1,
            instanceId=instance_id, regionId=region.regionId, target=target)).status == "rejected"
    assert store.current(managed.swap.sessionId).version == 1


def test_covering_covering_collision_still_clamps_and_door_effects_are_preserved() -> None:
    rug = _small_product("covering", placementClass="floor-covering")
    source = _source(rug)
    room = rectangular_room_shell("rug-pair-room", 4, 4, 3)
    design = _design(room, (rug, rug), (
        Placement(instanceId="first", productId=rug.id, position=(-0.6, 0, 0), yaw=0),
        Placement(instanceId="second", productId=rug.id, position=(0.6, 0, 0), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "covering-session")
    managed = store.register(design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    region = store.nudge_region(managed.swap.sessionId, 1, "first")
    assert region.status == "available"
    assert max(point[0] for point in region.polygon) < 0.801
    assert store.nudge(NudgeRequest(sessionId=managed.swap.sessionId, expectedVersion=1,
        instanceId="first", regionId=region.regionId, target=(0.3, 0))).status == "rejected"

    # A walkable class never exempts a Product from a door's swing/clearance.
    door_design = _design(_two_door_room(), (rug,), (
        Placement(instanceId="rug", productId=rug.id, position=(-0.3, 0, -1.5), yaw=0),
    ))
    store = DesignSessionStore(source, id_factory=lambda: "door-rug-session")
    managed = store.register(door_design, "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    region = store.nudge_region(managed.swap.sessionId, 1, "rug")
    assert region.status == "available"
    for displacement in region.polygon:
        placement = managed.placements[0].model_copy(update={"position": (
            region.origin[0] + displacement[0] * 0.99, 0, region.origin[1] + displacement[1] * 0.99,
        )})
        assert validate_placement(rug, managed.room, placement).status == "fits"
    assert min(point[1] for point in region.polygon) > -1


def test_contact_tolerance_is_retained_only_while_physically_true() -> None:
    design = _fixture()
    placement = design.placements[0]
    retained = nudged_placement(design.products[0], design.room, placement,
        (placement.position[0], placement.position[2] + 0.009999))
    detached = nudged_placement(design.products[0], design.room, placement,
        (placement.position[0], placement.position[2] + 0.010001))
    assert retained.wallContacts == placement.wallContacts
    assert detached.wallContacts == () and detached.wallContact is None


def test_registration_detects_catalogue_change_during_out_of_lock_validation() -> None:
    class MutableCatalogue:
        version = catalogue.version
        def get(self, product_id): return catalogue.get(product_id)
        def list(self, query=None): return catalogue.list(query)
    source = MutableCatalogue()
    def changing_validator(source, design, clearance):
        result = validate_fixed_pose_design(source, design, clearance)
        source.version = "changed"
        return result
    store = DesignSessionStore(source, validator=changing_validator)
    refused = store.register(_fixture(), "bedroom")
    assert refused.swap.status == "unavailable"
    assert "Catalogue changed" in refused.swap.detail
    assert store.session_count() == 0


@pytest.mark.parametrize("mode", ["certificate-expiry", "session-expiry", "catalogue-change"])
def test_expiry_or_catalogue_change_during_region_compute_never_installs(monkeypatch, mode) -> None:
    class MutableCatalogue:
        version = catalogue.version
        def get(self, product_id): return catalogue.get(product_id)
        def list(self, query=None): return catalogue.list(query)
    source = MutableCatalogue()
    clock = [0.0]
    store = DesignSessionStore(source, clock=lambda: clock[0], ttl_seconds=300, id_factory=lambda: "inflight-expiry")
    managed = store.register(_fixture(), "bedroom")
    assert managed.swap is not None and managed.swap.status == "available"
    def changing_builder(*args, **kwargs):
        result = build_nudge_certificate(*args, **kwargs)
        if mode == "catalogue-change": source.version = "changed"
        else: clock[0] = 121 if mode == "certificate-expiry" else 301
        return result
    monkeypatch.setattr("api.swaps.build_nudge_certificate", changing_builder)
    result = store.nudge_region(managed.swap.sessionId, 1, "bed-against-north")
    assert result.status == {"certificate-expiry": "unavailable", "session-expiry": "expired-session", "catalogue-change": "catalogue-changed"}[mode]
    assert store.certificate_count() == 0
    assert managed.swap.version == 1
