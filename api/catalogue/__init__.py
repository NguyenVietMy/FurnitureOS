"""Catalogue contract and configured implementation."""
from .contract import Catalogue, CatalogueQuery
from .providers.abo import abo_products, dimension_evidence
from .static import StaticCatalogue

catalogue: Catalogue = StaticCatalogue(abo_products())

__all__ = ["Catalogue", "CatalogueQuery", "StaticCatalogue", "catalogue", "dimension_evidence"]
