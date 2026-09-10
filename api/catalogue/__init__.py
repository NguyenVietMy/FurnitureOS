"""Catalogue contract and configured implementation."""
from .contract import Catalogue, CatalogueEntry, CatalogueQuery
from .providers.abo import abo_entries, catalogue_version, dimension_evidence
from .static import StaticCatalogue

catalogue: Catalogue = StaticCatalogue(catalogue_version(), abo_entries())

__all__ = ["Catalogue", "CatalogueEntry", "CatalogueQuery", "StaticCatalogue", "catalogue", "dimension_evidence"]
