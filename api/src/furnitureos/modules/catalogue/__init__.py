"""Catalogue module — what the store sells, at its true size and its true price.

PUBLIC SURFACE. Everything another module may use is re-exported here; reaching past
this file is a boundary violation that test_module_boundaries.py catches.

Internals, and why they stay internal:
  item.py     the domain rules — true metres, whole dong. The invariants live here.
  models.py   the items table, including stock columns nothing renders
  service.py  reads, id resolution, seeding
  schemas.py  the wire format, which omits stock
  router.py   route wiring, mounted by the composition root
  seeds/      the placeholder catalogue (schema permanent, products not — issue 13)
"""

from furnitureos.modules.catalogue.item import (
    Item,
    ItemError,
    load_seed_items,
    parse_item,
)
from furnitureos.modules.catalogue.router import router
from furnitureos.modules.catalogue.schemas import ItemOut
from furnitureos.modules.catalogue.service import list_items, resolve_items, seed_items

__all__ = [
    "Item",
    "ItemError",
    "ItemOut",
    "list_items",
    "load_seed_items",
    "parse_item",
    "resolve_items",
    "router",
    "seed_items",
]
