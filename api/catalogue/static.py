"""In-memory implementation of the provider-neutral Catalogue."""
from __future__ import annotations

from collections.abc import Iterable

from api.models import Product

from .contract import CatalogueQuery


class StaticCatalogue:
    def __init__(self, products: Iterable[Product]) -> None:
        ordered = tuple(products)
        by_id: dict[str, Product] = {}
        for product in ordered:
            if product.id in by_id:
                raise ValueError(f'Duplicate Product id "{product.id}" in the Catalogue')
            by_id[product.id] = product
        self._products = ordered
        self._by_id = by_id

    def list(self, query: CatalogueQuery | None = None) -> tuple[Product, ...]:
        query = query or CatalogueQuery()
        return tuple(product for product in self._products if
            (query.room_type is None or query.room_type in product.roomTypes)
            and (query.category is None or query.category == product.category)
            and (query.style_tag is None or query.style_tag in product.styleTags))

    def get(self, product_id: str) -> Product | None:
        return self._by_id.get(product_id)
