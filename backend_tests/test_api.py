from __future__ import annotations

from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


def validation_body(design: dict) -> dict:
    return {"product": design["product"], "room": design["room"], "placement": design["fit"]["placement"]}


def test_health_is_typed(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_preview_is_a_complete_api_backed_design(client) -> None:
    response = client.get("/api/preview-design")
    assert response.status_code == 200
    design = response.json()
    assert design["fit"]["status"] == "fits"
    assert design["product"]["frontAxis"] == "+z"
    assert design["fit"]["placement"]["wallContact"] == {"wallId": "wall-north", "face": "back"}
    assert design["room"].keys() == {"id", "floorPolygon", "walls", "ceilingHeightM", "openings"}
    assert design["room"]["openings"] == []
    assert design["product"]["purchase"].keys() == {"availability", "checkedOn", "note"}
    assert design["product"]["attribution"]["materialUrl"].startswith("https://")


def test_preview_is_byte_deterministic(client) -> None:
    assert client.get("/api/preview-design").content == client.get("/api/preview-design").content


def test_catalogue_gallery_is_absent_from_the_default_application(client) -> None:
    assert client.get("/api/catalogue-gallery").status_code == 404


def test_controlled_catalogue_gallery_exposes_products_but_not_private_styles() -> None:
    controlled = TestClient(create_app(enable_catalogue_gallery=True))
    response = controlled.get("/api/catalogue-gallery")
    assert response.status_code == 200
    body = response.json()
    assert body["catalogueVersion"]
    assert len(body["products"]) == 20
    serialized = response.text
    assert "privateStyle" not in serialized
    assert "Warm Minimal" not in serialized


def test_validation_accepts_the_preview_placement(client, design_body) -> None:
    response = client.post("/api/placement-validation", json=validation_body(design_body))
    assert response.status_code == 200
    assert response.json()["status"] == "fits"


def test_validation_reports_an_oversized_product(client, design_body) -> None:
    body = validation_body(design_body)
    body["product"]["id"] = "oversized-bed"
    body["product"]["dimensionsM"] = {"widthM": 4.5, "heightM": 1.4, "depthM": 3.5}
    body["product"]["accessRegions"] = [
        {"face": "front", "depthM": 0.6, "required": True, "purpose": "walking past the foot"}
    ]
    body["placement"]["productId"] = "oversized-bed"
    body["placement"]["position"] = [0, 0, 0.25]
    response = client.post("/api/placement-validation", json=body)
    assert response.status_code == 200
    assert response.json()["reason"] == "product-exceeds-room-bounds"


def test_validation_rejects_a_self_intersecting_room_shell(client, design_body) -> None:
    body = validation_body(deepcopy(design_body))
    points = [
        [3, 0],
        [-2.427050983124842, 1.7633557568774196],
        [0.9270509831248424, -2.853169548885461],
        [0.9270509831248417, 2.853169548885461],
        [-2.4270509831248432, -1.7633557568774187],
    ]
    body["room"] = {
        "id": "self-crossing-star",
        "floorPolygon": points,
        "walls": [
            {"id": f"stable-edge-{index}", "label": "Wall", "start": point, "end": points[(index + 1) % len(points)]}
            for index, point in enumerate(points)
        ],
        "ceilingHeightM": 2.5,
    }
    body["product"]["dimensionsM"] = {"widthM": 0.1, "heightM": 1, "depthM": 0.1}
    body["product"]["accessRegions"] = []
    body["placement"]["position"] = [0, 0, 0]
    body["placement"]["wallContact"] = None

    response = client.post("/api/placement-validation", json=body)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("reverse", [False, True])
def test_validation_accepts_simple_convex_rooms_in_both_windings(client, design_body, reverse) -> None:
    body = validation_body(deepcopy(design_body))
    points = [[-2, -1.5], [-2, 1.5], [2, 1.5], [2, -1.5]]
    if reverse:
        points.reverse()
    body["room"]["floorPolygon"] = points
    body["room"]["walls"] = [
        {"id": f"capture-wall-{index + 10}", "label": "Captured wall", "start": point, "end": points[(index + 1) % len(points)]}
        for index, point in enumerate(points)
    ]
    body["product"]["dimensionsM"] = {"widthM": 0.5, "heightM": 1, "depthM": 0.5}
    body["product"]["accessRegions"] = []
    body["placement"]["wallContact"] = None
    body["placement"]["position"] = [0, 0, 0]

    response = client.post("/api/placement-validation", json=body)

    assert response.status_code == 200
    assert response.json()["status"] == "fits"


@pytest.mark.parametrize("field,value", [
    ("yaw", "NaN"), ("yaw", "Infinity"), ("position", [0, "NaN", 0]),
    ("position", [0, 0]), ("productId", ""), ("extra", 1),
])
def test_validation_rejects_malformed_placement(client, design_body, field, value) -> None:
    body = validation_body(deepcopy(design_body))
    body["placement"][field] = value
    assert client.post("/api/placement-validation", json=body).status_code == 422


@pytest.mark.parametrize(
    "path,token",
    [
        (("placement", "yaw"), "1e999"),
        (("placement", "position", 0), "Infinity"),
        (("product", "dimensionsM", "widthM"), "NaN"),
        (("room", "ceilingHeightM"), "1e999"),
        (("room", "floorPolygon", 0, 0), "-Infinity"),
    ],
)
def test_validation_returns_json_safe_422_for_numeric_nonfinite_input(client, design_body, path, token) -> None:
    body = validation_body(deepcopy(design_body))
    current = body
    for part in path[:-1]:
        current = current[part]
    marker = "__NONFINITE_NUMBER__"
    current[path[-1]] = marker
    raw = json.dumps(body, separators=(",", ":")).replace(f'"{marker}"', token).encode()

    response = client.post(
        "/api/placement-validation",
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload["detail"], list)
    assert payload["detail"]


@pytest.mark.parametrize("section", ["product", "room", "placement"])
def test_validation_rejects_missing_contract_sections(client, design_body, section) -> None:
    body = validation_body(deepcopy(design_body))
    body[section] = {}
    assert client.post("/api/placement-validation", json=body).status_code == 422


def test_validation_rejects_a_product_id_mismatch(client, design_body) -> None:
    body = validation_body(design_body)
    body["placement"]["productId"] = "different-product"
    response = client.post("/api/placement-validation", json=body)
    assert response.status_code == 422
    assert "must match" in response.json()["detail"]


@pytest.mark.parametrize("y,reason", [
    (0.002, None), (-0.002, None), (0.0021, "not-resting-on-floor"),
    (-0.0021, "not-resting-on-floor"), (1.25, "not-resting-on-floor"),
])
def test_validation_enforces_the_floor_centre_origin(client, design_body, y, reason) -> None:
    body = validation_body(design_body)
    body["placement"]["position"][1] = y
    result = client.post("/api/placement-validation", json=body).json()
    assert result["status"] == ("fits" if reason is None else "invalid-fit")
    if reason:
        assert result["reason"] == reason


def test_validation_uses_the_placed_top_for_ceiling_checks(client, design_body) -> None:
    body = validation_body(design_body)
    body["room"]["ceilingHeightM"] = 1.426
    body["placement"]["position"][1] = 0.002
    assert client.post("/api/placement-validation", json=body).json()["reason"] == "exceeds-ceiling-height"


def test_wall_relative_fixture_catalogue_is_visible_and_typed(client) -> None:
    response = client.get("/api/design-fixtures")

    assert response.status_code == 200
    fixtures = response.json()["fixtures"]
    assert [fixture["id"] for fixture in fixtures] == [
        "against-wall",
        "centred-on-wall",
        "in-corner",
        "door-swing-failure",
        "matching-nightstands",
    ]
    assert [fixture["intentKind"] for fixture in fixtures] == [
        "against",
        "centred_on",
        "in_corner",
        "in_corner",
        "centred_on",
    ]
    assert [fixture["expectedOutcome"] for fixture in fixtures] == [
        "solved",
        "solved",
        "solved",
        "failed",
        "solved",
    ]


@pytest.mark.parametrize(
    "fixture_id,product_id,position",
    [
        ("against-wall", "bed-prudence-tufted-queen-natural", [-0.5, 0.0, -0.383505]),
        ("centred-on-wall", "dresser-stylistics-campaign-white", [0.0, 0.0, 1.2699075]),
        ("in-corner", "nightstand-alkove-hayes-wild-oak", [-1.720092, 0.0, -1.280036]),
    ],
)
def test_fastapi_resolves_fixture_ids_to_catalogue_products_and_literal_placements(
    client,
    fixture_id,
    product_id,
    position,
) -> None:
    response = client.post("/api/design-resolution", json={"fixtureId": fixture_id, "maxCandidates": 128})

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "solved"
    assert result["products"][0]["id"] == product_id
    assert result["placements"][0]["productId"] == product_id
    assert result["placements"][0]["position"] == pytest.approx(position, abs=1e-6)


def test_fastapi_returns_clear_typed_fixture_failure_without_partial_design(client) -> None:
    result = client.post(
        "/api/design-resolution",
        json={"fixtureId": "door-swing-failure", "maxCandidates": 128},
    ).json()

    assert result["status"] == "failed"
    assert result["reason"] == "door-swing-exclusion"
    assert result["failedIntentId"] == "blocked-nightstand"
    assert "placements" not in result
    assert "bedroom-door" in result["detail"]


def test_matching_nightstands_fixture_returns_two_instances_of_one_product(client) -> None:
    response = client.post(
        "/api/design-resolution",
        json={"fixtureId": "matching-nightstands", "maxCandidates": 128},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "solved"
    assert [product["id"] for product in result["products"]] == [
        "nightstand-alkove-hayes-wild-oak",
        "nightstand-alkove-hayes-wild-oak",
    ]
    assert [placement["instanceId"] for placement in result["placements"]] == [
        "matching-nightstand-north",
        "matching-nightstand-south",
    ]
    assert result["placements"][0]["position"] != result["placements"][1]["position"]


def test_fastapi_returns_typed_unknown_fixture_and_bounds_search_input(client) -> None:
    unknown = client.post(
        "/api/design-resolution",
        json={"fixtureId": "no-such-fixture", "maxCandidates": 128},
    )
    assert unknown.status_code == 200
    assert unknown.json()["reason"] == "unknown-fixture-reference"

    for invalid_limit in (0, 257):
        response = client.post(
            "/api/design-resolution",
            json={"fixtureId": "against-wall", "maxCandidates": invalid_limit},
        )
        assert response.status_code == 422


def test_fastapi_accepts_coordinate_free_intents_and_uses_catalogue_facts(client) -> None:
    body = {
        "room": {
            "id": "http-room",
            "floorPolygon": [[-2, -1.5], [-2, 1.5], [2, 1.5], [2, -1.5]],
            "walls": [
                {"id": "north", "label": "North", "start": [-2, -1.5], "end": [2, -1.5]},
                {"id": "east", "label": "East", "start": [2, -1.5], "end": [2, 1.5]},
                {"id": "south", "label": "South", "start": [2, 1.5], "end": [-2, 1.5]},
                {"id": "west", "label": "West", "start": [-2, 1.5], "end": [-2, -1.5]},
            ],
            "ceilingHeightM": 2.5,
            "openings": [],
        },
        "intents": [{
            "id": "http-centred-bed",
            "kind": "centred_on",
            "productId": "bed-prudence-tufted-queen-natural",
            "wallId": "north",
            "face": "back",
        }],
        "maxCandidates": 32,
    }
    assert "position" not in body["intents"][0]
    assert "yaw" not in body["intents"][0]

    response = client.post("/api/design-solve", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "solved"
    assert result["placements"][0]["position"] == pytest.approx([0.0, 0.0, -0.383505], abs=1e-6)
    assert result["products"][0]["dimensionsM"] == {
        "widthM": 1.695826,
        "heightM": 1.425926,
        "depthM": 2.23299,
    }


def test_design_solve_returns_typed_failure_when_derived_centre_crosses_public_bound() -> None:
    points = [[999, -2], [999, 2], [1000, 2], [1000, -2]]
    body = {
        "room": {
            "id": "near-positive-x-bound",
            "floorPolygon": points,
            "walls": [
                {"id": wall_id, "label": wall_id, "start": point, "end": points[(index + 1) % 4]}
                for index, (wall_id, point) in enumerate(zip(("west", "south", "east", "north"), points, strict=True))
            ],
            "ceilingHeightM": 2.5,
            "openings": [],
        },
        "intents": [{
            "id": "bounded-centred-bed",
            "kind": "centred_on",
            "productId": "bed-prudence-tufted-queen-natural",
            "wallId": "west",
            "face": "back",
        }],
        "maxCandidates": 4,
    }
    no_raise_client = TestClient(create_app(), raise_server_exceptions=False)

    response = no_raise_client.post("/api/design-solve", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert result["reason"] == "intent-unsatisfiable"
    assert result["failedIntentId"] == "bounded-centred-bed"
    assert result["search"] == {
        "attemptedCandidates": 1,
        "candidateLimit": 4,
        "exhaustive": True,
    }


@pytest.mark.parametrize(
    "points,wall_id",
    [
        ([[-1000, -2], [-1000, 2], [-999, 2], [-999, -2]], "east"),
        ([[-2, 999], [-2, 1000], [2, 1000], [2, 999]], "north"),
        ([[-2, -1000], [-2, -999], [2, -999], [2, -1000]], "south"),
    ],
)
def test_design_solve_handles_mirrored_and_rotated_derived_centres_at_public_bounds(
    points,
    wall_id,
) -> None:
    body = {
        "room": {
            "id": f"near-{wall_id}-coordinate-bound",
            "floorPolygon": points,
            "walls": [
                {"id": candidate, "label": candidate, "start": point, "end": points[(index + 1) % 4]}
                for index, (candidate, point) in enumerate(zip(("west", "south", "east", "north"), points, strict=True))
            ],
            "ceilingHeightM": 2.5,
            "openings": [],
        },
        "intents": [{
            "id": "bounded-centred-bed",
            "kind": "centred_on",
            "productId": "bed-prudence-tufted-queen-natural",
            "wallId": wall_id,
            "face": "back",
        }],
        "maxCandidates": 4,
    }
    no_raise_client = TestClient(create_app(), raise_server_exceptions=False)

    response = no_raise_client.post("/api/design-solve", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert result["reason"] == "intent-unsatisfiable"
    assert result["search"] == {
        "attemptedCandidates": 1,
        "candidateLimit": 4,
        "exhaustive": True,
    }


@pytest.mark.parametrize(
    "kind,points,wall_id,adjacent_wall_id,product_id,expected_reason",
    [
        (
            "against",
            [[999.9, -0.2], [999.9, 0.2], [1000, 0.2], [1000, -0.2]],
            "west",
            None,
            "bed-prudence-tufted-queen-natural",
            "intent-unsatisfiable",
        ),
        (
            "in_corner",
            [[999.9, -1], [999.9, 1], [1000, 1], [1000, -1]],
            "west",
            "north",
            "nightstand-alkove-hayes-wild-oak",
            "intent-unsatisfiable",
        ),
        (
            "in_corner",
            [[-1000, -1], [-1000, 1], [-999.9, 1], [-999.9, -1]],
            "east",
            "south",
            "nightstand-alkove-hayes-wild-oak",
            "intent-unsatisfiable",
        ),
    ],
)
def test_design_solve_handles_derived_centres_for_all_wall_relative_intents(
    kind,
    points,
    wall_id,
    adjacent_wall_id,
    product_id,
    expected_reason,
) -> None:
    intent = {
        "id": f"bounded-{kind}",
        "kind": kind,
        "productId": product_id,
        "wallId": wall_id,
        "face": "back",
    }
    if adjacent_wall_id is not None:
        intent["adjacentWallId"] = adjacent_wall_id
    body = {
        "room": {
            "id": f"near-bound-{kind}",
            "floorPolygon": points,
            "walls": [
                {"id": candidate, "label": candidate, "start": point, "end": points[(index + 1) % 4]}
                for index, (candidate, point) in enumerate(zip(("west", "south", "east", "north"), points, strict=True))
            ],
            "ceilingHeightM": 2.5,
            "openings": [],
        },
        "intents": [intent],
        "maxCandidates": 4,
    }
    no_raise_client = TestClient(create_app(), raise_server_exceptions=False)

    response = no_raise_client.post("/api/design-solve", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert result["reason"] == expected_reason
    assert result["failedIntentId"] == intent["id"]
    assert result["search"] == {
        "attemptedCandidates": 1,
        "candidateLimit": 4,
        "exhaustive": True,
    }


@pytest.mark.parametrize(
    "centre_x,access_face,expected_reason",
    [
        (999.9, None, "footprint-outside-room"),
        (-999.9, None, "footprint-outside-room"),
        (999.7, "right", "access-region-outside-room"),
        (-999.7, "left", "access-region-outside-room"),
    ],
)
def test_placement_validation_returns_typed_failure_for_derived_geometry_beyond_public_bounds(
    client,
    design_body,
    centre_x,
    access_face,
    expected_reason,
) -> None:
    body = validation_body(deepcopy(design_body))
    minimum_x, maximum_x = ((998, 1000) if centre_x > 0 else (-1000, -998))
    points = [[minimum_x, -2], [minimum_x, 2], [maximum_x, 2], [maximum_x, -2]]
    body["room"]["id"] = "derived-geometry-bound"
    body["room"]["floorPolygon"] = points
    body["room"]["walls"] = [
        {"id": f"bound-wall-{index}", "label": "Bound wall", "start": point, "end": points[(index + 1) % 4]}
        for index, point in enumerate(points)
    ]
    body["room"]["openings"] = []
    body["product"]["id"] = "bounded-derived-product"
    body["product"]["dimensionsM"] = {"widthM": 0.4, "heightM": 1, "depthM": 0.2}
    body["product"]["accessRegions"] = [] if access_face is None else [{
        "face": access_face,
        "depthM": 0.4,
        "required": True,
        "purpose": "using the furniture",
    }]
    body["placement"]["productId"] = body["product"]["id"]
    body["placement"]["position"] = [centre_x, 0, 0]
    body["placement"]["wallContact"] = None

    response = client.post("/api/placement-validation", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "invalid-fit"
    assert result["reason"] == expected_reason


def test_fastapi_intent_endpoint_returns_typed_unknown_references(client) -> None:
    body = {
        "room": {
            "id": "http-room",
            "floorPolygon": [[-2, -1.5], [-2, 1.5], [2, 1.5], [2, -1.5]],
            "walls": [
                {"id": "north", "label": "North", "start": [-2, -1.5], "end": [2, -1.5]},
                {"id": "east", "label": "East", "start": [2, -1.5], "end": [2, 1.5]},
                {"id": "south", "label": "South", "start": [2, 1.5], "end": [-2, 1.5]},
                {"id": "west", "label": "West", "start": [-2, 1.5], "end": [-2, -1.5]},
            ],
            "ceilingHeightM": 2.5,
            "openings": [],
        },
        "intents": [{"id": "missing", "kind": "against", "productId": "missing", "wallId": "north"}],
        "maxCandidates": 32,
    }

    response = client.post("/api/design-solve", json=body)

    assert response.status_code == 200
    assert response.json()["reason"] == "unknown-product-reference"


def design_solve_body(client) -> dict:
    room = client.get("/api/preview-design").json()["room"]
    return {
        "room": room,
        "intents": [{
            "id": "bounded-room",
            "kind": "centred_on",
            "productId": "nightstand-alkove-hayes-wild-oak",
            "wallId": "wall-north",
        }],
        "maxCandidates": 1,
    }


def test_design_solve_rejects_huge_finite_coordinates_before_geometry_work(client) -> None:
    body = design_solve_body(client)
    body["room"]["floorPolygon"][0][0] = -1e308
    body["room"]["walls"][0]["start"][0] = -1e308
    body["room"]["walls"][3]["end"][0] = -1e308

    response = client.post("/api/design-solve", json=body)

    assert response.status_code == 422
    assert any(error["type"] in {"less_than_equal", "greater_than_equal"} for error in response.json()["detail"])


def test_design_solve_rejects_a_large_finite_wall_span(client) -> None:
    body = design_solve_body(client)
    points = [[-600, -2], [-600, 2], [600, 2], [600, -2]]
    body["room"]["floorPolygon"] = points
    body["room"]["walls"] = [
        {"id": f"wall-{index}", "label": "Wall", "start": point, "end": points[(index + 1) % 4]}
        for index, point in enumerate(points)
    ]
    body["intents"][0]["wallId"] = "wall-3"

    response = client.post("/api/design-solve", json=body)

    assert response.status_code == 422
    assert "maximum 1000" in response.text


@pytest.mark.parametrize("field,oversized", [
    ("floorPolygon", [[0, 0]] * 65),
    ("walls", [{"id": "duplicate", "label": "Wall", "start": [0, 0], "end": [1, 0]}] * 65),
    ("openings", [{
        "id": "duplicate",
        "kind": "window",
        "wallId": "wall-north",
        "offsetAlongWallM": 0,
        "widthM": 1,
        "bottomM": 1,
        "heightM": 1,
        "clearanceDepthM": 0.2,
    }] * 129),
])
def test_design_solve_rejects_oversized_room_collections_before_polygon_validation(
    client,
    field,
    oversized,
) -> None:
    body = design_solve_body(client)
    body["room"][field] = oversized

    response = client.post("/api/design-solve", json=body)

    assert response.status_code == 422
    assert any(error["type"] == "too_long" for error in response.json()["detail"])


def test_design_solve_allows_repeated_catalogue_products_as_distinct_instances(client) -> None:
    body = design_solve_body(client)
    points = [[-3, -3], [-3, 3], [3, 3], [3, -3]]
    body["room"]["floorPolygon"] = points
    body["room"]["walls"] = [
        {"id": wall_id, "label": wall_id, "start": points[index], "end": points[(index + 1) % 4]}
        for index, wall_id in enumerate(("west", "south", "east", "north"))
    ]
    body["intents"] = [
        {"id": "instance-north", "kind": "centred_on", "productId": "nightstand-alkove-hayes-wild-oak", "wallId": "north"},
        {"id": "instance-south", "kind": "centred_on", "productId": "nightstand-alkove-hayes-wild-oak", "wallId": "south"},
    ]
    body["maxCandidates"] = 4

    response = client.post("/api/design-solve", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "solved"
    assert [product["id"] for product in result["products"]] == [
        "nightstand-alkove-hayes-wild-oak",
        "nightstand-alkove-hayes-wild-oak",
    ]
    assert [placement["instanceId"] for placement in result["placements"]] == [
        "instance-north",
        "instance-south",
    ]
