"""Provider-neutral Catalogue interface from ADR-0001."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from api.models import Product, ProductCategory, RoomType


@dataclass(frozen=True)
class CatalogueQuery:
    room_type: RoomType | None = None
    category: ProductCategory | None = None
    private_style_id: str | None = None


@dataclass(frozen=True)
class CatalogueEntry:
    """One public Product plus server-private curation metadata."""

    product: Product
    private_style_ids: tuple[str, ...]


class Catalogue(Protocol):
    @property
    def version(self) -> str: ...
    def list(self, query: CatalogueQuery | None = None) -> tuple[Product, ...]: ...
    def get(self, product_id: str) -> Product | None: ...
    def private_style_ids(self, product_id: str) -> tuple[str, ...]: ...
