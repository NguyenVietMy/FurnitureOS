"""`GET /api/items` — everything the catalogue panel draws, and nothing else.

The stock columns exist in the schema and are deliberately absent from the wire. Nothing
in v1 renders them, and a number nobody maintains is worse on screen than no number.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from furnitureos.core.db import get_session
from furnitureos.main import app
from furnitureos.modules.catalogue import seed_items


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    seed_items(session)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_lists_the_whole_catalogue(client: TestClient) -> None:
    response = client.get("/api/items")

    assert response.status_code == 200
    assert len(response.json()) >= 15


def test_item_carries_what_the_panel_and_the_scene_need(client: TestClient) -> None:
    [item, *_] = client.get("/api/items").json()

    assert item["id"]
    assert item["name"]
    assert item["category"]
    assert item["preset_ref"]
    assert item["width_m"] > 0
    assert item["depth_m"] > 0
    assert item["height_m"] > 0
    assert item["price_vnd"] > 0


def test_stock_is_never_exposed(client: TestClient) -> None:
    """The columns are real; the wire format is not. Do not add them without a screen."""
    for item in client.get("/api/items").json():
        assert "stock_qty" not in item
        assert "lead_time_days" not in item


def test_prices_are_whole_numbers_on_the_wire(client: TestClient) -> None:
    """JSON has one number type. Serving 12500000.0 invites a float path in the client."""
    for item in client.get("/api/items").json():
        assert isinstance(item["price_vnd"], int)


def test_categories_are_grouped_so_chips_come_out_in_order(client: TestClient) -> None:
    body = client.get("/api/items").json()

    keys = [(item["category"], item["name"]) for item in body]
    assert keys == sorted(keys)


def test_an_unseeded_catalogue_is_an_empty_list_not_a_404(session: Session) -> None:
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        response = test_client.get("/api/items")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []
