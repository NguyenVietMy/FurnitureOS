"""Single import point for every ORM model.

Alembic autogeneration and test table creation both need every model registered on
Base.metadata. Importing this module guarantees that regardless of import order, so add
a line here whenever a module gains a table.
"""

from furnitureos.modules.catalogue.models import ItemRow
from furnitureos.modules.units.models import UnitRow

__all__ = ["ItemRow", "UnitRow"]
