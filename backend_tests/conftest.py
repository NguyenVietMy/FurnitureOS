from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from api.catalogue import catalogue
from api.design import FEATURED_PRODUCT_ID, bedroom_design, bedroom_room_shell
from api.main import application as app
from api.models import Product


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def product() -> Product:
    value = catalogue.get(FEATURED_PRODUCT_ID)
    assert value is not None
    return value


@pytest.fixture
def room():
    return bedroom_room_shell()


@pytest.fixture
def design_body() -> dict:
    return bedroom_design().model_dump(mode="json")


def product_variant(product: Product, **updates: object) -> Product:
    value = deepcopy(product.model_dump(mode="json"))
    value.update(updates)
    return Product.model_validate(value)
