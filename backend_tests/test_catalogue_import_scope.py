"""Metadata codecs must not load an unrelated activated Product union."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def child(code):
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=60)


def test_metadata_adapter_imports_do_not_read_published_product_files():
    result = child('''
import pathlib, sys
products = (pathlib.Path.cwd() / 'public/products').resolve()
def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        value = pathlib.Path(args[0]).resolve()
        if value.is_relative_to(products):
            raise AssertionError('Metadata-only import read published Product: ' + str(value))
sys.addaudithook(guard)
from api.catalogue.contract import CatalogueEntry, CatalogueQuery
from api.catalogue.providers.abo import AssetManifest, SeedCatalogue, LivingCandidateCatalogue, entry_from_manifest
from api.catalogue.providers.expansion import ExpansionBatch
from api.catalogue.static import StaticCatalogue
print('METADATA_TYPES_IMPORTED_WITHOUT_PUBLISHED_DATA')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'METADATA_TYPES_IMPORTED_WITHOUT_PUBLISHED_DATA'


def test_requesting_configured_catalogue_still_fails_closed_on_bad_expansion_read():
    # Read failure at the real loader boundary, without changing published bytes.
    result = child('''
from pathlib import Path
from unittest.mock import patch
from api.catalogue.providers.expansion import CatalogueExpansionError
assert Path('api/catalogue/providers/expansion/index.json').exists()
with patch('api.catalogue.providers.expansion.safe_read', side_effect=OSError('controlled failed read')):
    try:
        from api.catalogue import catalogue
    except CatalogueExpansionError:
        print('CONFIGURED_CATALOGUE_FAILED_CLOSED')
    else:
        raise AssertionError('Configured Catalogue bypassed expansion validation')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'CONFIGURED_CATALOGUE_FAILED_CLOSED'
