"""Catalogue contract and configured implementation."""
from .contract import Catalogue, CatalogueEntry, CatalogueQuery
from .providers.abo import abo_entries, catalogue_version, dimension_evidence
from .static import StaticCatalogue
from .providers.living import reviewed_entries, REVIEWED_PATH
from hashlib import sha256

_entries = reviewed_entries(abo_entries())
_version = catalogue_version()
if len(_entries) > 20:
    _version += "+living-" + sha256(REVIEWED_PATH.read_bytes()).hexdigest()[:16]
catalogue: Catalogue = StaticCatalogue(_version, _entries)

__all__ = ["Catalogue", "CatalogueEntry", "CatalogueQuery", "StaticCatalogue", "catalogue", "dimension_evidence"]
