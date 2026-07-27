"""Units module — apartment geometry: what shape the buyer is furnishing.

PUBLIC SURFACE. Everything another module may use is re-exported here. Reaching past
this file into `furnitureos.modules.units.service` (or worse, `.models`) from another
module is a boundary violation; test_module_boundaries.py enforces it.

Internals, and why they stay internal:
  plan.py     geometry parsing and validation — the invariants live here
  models.py   the units table — only this module may touch its storage
  service.py  reads and seeding
  schemas.py  the HTTP wire format
  router.py   route wiring, mounted by the composition root
"""

from furnitureos.modules.units.plan import (
    Opening,
    Room,
    UnitPlan,
    UnitPlanError,
    Wall,
    load_seed_unit,
    parse_unit_plan,
)
from furnitureos.modules.units.router import router
from furnitureos.modules.units.schemas import UnitOut
from furnitureos.modules.units.service import get_unit, list_unit_slugs, seed_units

__all__ = [
    "Opening",
    "Room",
    "UnitOut",
    "UnitPlan",
    "UnitPlanError",
    "Wall",
    "get_unit",
    "list_unit_slugs",
    "load_seed_unit",
    "parse_unit_plan",
    "router",
    "seed_units",
]
