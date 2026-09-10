"""In-memory implementation of the provider-neutral Catalogue."""
from __future__ import annotations

from collections.abc import Iterable

from api.models import Product

from .contract import CatalogueEntry, CatalogueQuery


class StaticCatalogue:
    def __init__(self, version: str, entries: Iterable[CatalogueEntry]) -> None:
        if not version.strip():
            raise ValueError("Catalogue version cannot be blank")
        ordered_entries = tuple(entries)
        by_id: dict[str, CatalogueEntry] = {}
        for entry in ordered_entries:
            product = entry.product
            if product.id in by_id:
                raise ValueError(f'Duplicate Product id "{product.id}" in the Catalogue')
            if not entry.private_style_ids or len(set(entry.private_style_ids)) != len(entry.private_style_ids):
                raise ValueError(f'Product "{product.id}" needs unique private Style ids')
            by_id[product.id] = entry
        self._version = version
        self._entries = ordered_entries
        self._by_id = by_id

    @property
    def version(self) -> str:
        return self._version

    def list(self, query: CatalogueQuery | None = None) -> tuple[Product, ...]:
        query = query or CatalogueQuery()
        return tuple(entry.product for entry in self._entries if
            (product := entry.product)
            and
            (query.room_type is None or query.room_type in product.roomTypes)
            and (query.category is None or query.category == product.category)
            and (query.private_style_id is None or query.private_style_id in entry.private_style_ids))

    def get(self, product_id: str) -> Product | None:
        entry = self._by_id.get(product_id)
        return entry.product if entry else None

    def private_style_ids(self, product_id: str) -> tuple[str, ...]:
        entry = self._by_id.get(product_id)
        return entry.private_style_ids if entry else ()
