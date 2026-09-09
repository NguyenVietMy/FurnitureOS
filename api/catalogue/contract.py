"""Provider-neutral Catalogue interface from ADR-0001."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from api.models import Product, ProductCategory, RoomType


@dataclass(frozen=True)
class CatalogueQuery:
    room_type: RoomType | None = None
    category: ProductCategory | None = None
    style_tag: str | None = None


class Catalogue(Protocol):
    def list(self, query: CatalogueQuery | None = None) -> tuple[Product, ...]: ...
    def get(self, product_id: str) -> Product | None: ...
