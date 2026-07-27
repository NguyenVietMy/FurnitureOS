"""The units HTTP surface: the gallery's list and the renderer's detail.

`GET /api/units/{slug}` carries derived walls, not just the raw outline. Wall ids are
what openings reference, so the server owns wall *identity* and the client owns wall
*geometry* (extrusion, opening cutouts). Deriving ids on both sides would let the two
drift apart silently.

`GET /api/units` is the gallery's list. It is a genuinely different projection, not the
detail endpoint with a loop around it: cards need display metadata and an outline to
draw a thumbnail from, and shipping every wall and opening for every unit would grow
the payload with the catalogue for no one's benefit.
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


# --- GET /api/units — the gallery's list ------------------------------------------


def test_list_is_public_and_returns_every_unit(client: TestClient) -> None:
    """No login, no unit-number lookup: the gallery is the front door of the funnel."""
    response = client.get("/api/units")

    assert response.status_code == 200
    assert [summary["slug"] for summary in response.json()] == ["sunrise-b"]


def test_list_carries_the_metadata_a_card_shows(client: TestClient) -> None:
    [summary] = client.get("/api/units").json()

    assert summary["name"] == "Type B"
    assert summary["building"] == "Sunrise Tower"
    assert summary["bedrooms"] == 2
    assert summary["area_m2"] == pytest.approx(74.0)


def test_list_carries_the_polygons_a_thumbnail_draws(client: TestClient) -> None:
    [summary] = client.get("/api/units").json()

    assert len(summary["outline"]) >= 3
    assert len(summary["rooms"]) == 5
    assert all(len(room["polygon"]) >= 3 for room in summary["rooms"])


def test_list_omits_what_only_the_renderer_needs(client: TestClient) -> None:
    """Walls and openings are per-unit detail. The gallery would carry them for nothing."""
    [summary] = client.get("/api/units").json()

    assert "walls" not in summary
    assert "openings" not in summary


def test_list_and_detail_agree_on_derived_metadata(client: TestClient) -> None:
    """Both derive from the same plan, so a card can never contradict the page it opens."""
    [summary] = client.get("/api/units").json()
    detail = client.get(f"/api/units/{summary['slug']}").json()

    assert summary["area_m2"] == detail["area_m2"]
    assert summary["bedrooms"] == detail["bedrooms"]
    assert summary["outline"] == detail["outline"]


def test_the_list_route_does_not_shadow_the_detail_route(client: TestClient) -> None:
    """`/api/units` and `/api/units/{slug}` are neighbours; a greedy path would eat one."""
    assert client.get("/api/units").status_code == 200
    assert client.get("/api/units/sunrise-b").status_code == 200
    assert client.get("/api/units/nope").status_code == 404
