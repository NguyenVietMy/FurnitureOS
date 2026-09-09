from __future__ import annotations

from copy import deepcopy
import json

import pytest


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
    assert design["room"].keys() == {"id", "floorPolygon", "walls", "ceilingHeightM"}
    assert design["product"]["purchase"].keys() == {"availability", "checkedOn", "note"}
    assert design["product"]["attribution"]["materialUrl"].startswith("https://")


def test_preview_is_byte_deterministic(client) -> None:
    assert client.get("/api/preview-design").content == client.get("/api/preview-design").content


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
