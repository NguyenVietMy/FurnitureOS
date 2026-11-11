"""Catalogue types and an explicitly requested, validated runtime singleton.

Importing a metadata codec must not read every published Mesh. The application
requests ``catalogue`` through the same public import and gets the complete,
fail-closed configured union before serving any request.
"""
from threading import RLock

from .contract import Catalogue, CatalogueEntry, CatalogueQuery
from .providers.abo import dimension_evidence
from .static import StaticCatalogue

# A module reload must also rebuild the configured union on its next request.
globals().pop('catalogue', None)
_catalogue_lock = RLock()


def _configured_catalogue() -> Catalogue:
    from hashlib import sha256
    from .providers.abo import abo_entries, catalogue_version, seed_catalogue, LivingCandidateCatalogue
    from .providers.living import reviewed_entries, REVIEWED_PATH
    from .providers.expansion import expanded_entries

    entries = reviewed_entries(abo_entries())
    version = catalogue_version()
    if len(entries) > 20:
        version += "+living-" + sha256(REVIEWED_PATH.read_bytes()).hexdigest()[:16]
    records = {r.productId: r for r in seed_catalogue().products}
    if len(entries) > 20:
        living = LivingCandidateCatalogue.model_validate_json(REVIEWED_PATH.with_name('abo-living-candidates.json').read_bytes())
        records.update({r.productId: r for r in living.products if any(e.product.id == r.productId for e in entries)})
    entries, version = expanded_entries(entries, version, tuple(records.values()))
    return StaticCatalogue(version, entries)


def __getattr__(name: str):
    if name != 'catalogue':
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    with _catalogue_lock:
        value = globals().get('catalogue')
        if value is None:
            value = _configured_catalogue()
            globals()['catalogue'] = value
        return value

__all__ = ["Catalogue", "CatalogueEntry", "CatalogueQuery", "StaticCatalogue", "catalogue", "dimension_evidence"]
