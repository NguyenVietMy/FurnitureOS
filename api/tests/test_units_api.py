"""GET /api/units/{slug} — the payload the renderer draws from.

The response carries derived walls, not just the raw outline. Wall ids are what
openings reference, so the server owns wall *identity* and the client owns wall
*geometry* (extrusion, opening cutouts). Deriving ids on both sides would let the two
drift apart silently.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from furnitureos.core.db import get_session
from furnitureos.main import app
from furnitureos.modules.units import seed_units


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    seed_units(session)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_returns_the_seeded_unit(client: TestClient) -> None:
    response = client.get("/api/units/sunrise-b")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "sunrise-b"
    assert body["ceiling_height_m"] == pytest.approx(2.7)


def test_unknown_slug_is_a_404(client: TestClient) -> None:
    response = client.get("/api/units/nope")

    assert response.status_code == 404


def test_payload_carries_everything_the_renderer_needs(client: TestClient) -> None:
    body = client.get("/api/units/sunrise-b").json()

    assert len(body["outline"]) >= 3
    assert len(body["rooms"]) == 5
    assert len(body["walls"]) == 10
    assert body["openings"], "openings must be present or there is nothing to cut"


def test_walls_carry_the_ids_openings_reference(client: TestClient) -> None:
    body = client.get("/api/units/sunrise-b").json()

    wall_ids = {wall["id"] for wall in body["walls"]}
    for opening in body["openings"]:
        assert opening["wall"] in wall_ids


def test_walls_carry_endpoints_and_length(client: TestClient) -> None:
    body = client.get("/api/units/sunrise-b").json()

    for wall in body["walls"]:
        assert len(wall["start"]) == 2
        assert len(wall["end"]) == 2
        assert wall["length_m"] > 0
        assert wall["thickness_m"] > 0


def test_derived_metadata_is_served_not_stored(client: TestClient) -> None:
    body = client.get("/api/units/sunrise-b").json()

    assert body["area_m2"] == pytest.approx(74.0)
    assert body["bedrooms"] == 2


def test_healthcheck(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
