"""Configured package regression; the view must come from retained builder proof.

The subprocess uses this interpreter's installed dependencies, explicitly not a
claim that a Linux native dependency wheel has executed on Windows.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from api.catalogue import catalogue
from api.catalogue.contract import CatalogueQuery

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package_view():
    value = os.environ.get("FURNITUREOS_FUNCTION_VIEW")
    if not value:
        pytest.skip("Requires an external materialized Python package view")
    directory = Path(value).resolve(strict=True)
    assert not directory.is_relative_to(ROOT), "Package proof must be isolated from source"
    return directory


def test_python_package_separates_static_meshes_and_development_tools(package_view):
    for name in ("dist", "public/products", "public/decoders", "tools", "backend_tests", "e2e", "tests"):
        assert not (package_view / name).exists(), f"Unnecessary function payload: {name}"
    for name in ("api/index.py", "api/live-reference-manifest.json", "api/catalogue/providers/expansion/index.json"):
        assert (package_view / name).is_file(), f"Missing runtime authority input: {name}"


def test_packaged_api_loads_the_complete_identical_catalogue_and_verified_references(package_view):
    # -I removes CWD/PYTHONPATH; only the isolated view is added for app imports.
    # Environment values are controlled: no hosted credentials or provider calls.
    program = r'''
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import api.index,api.main
from api.catalogue import catalogue
from api.catalogue.contract import CatalogueQuery
from api.live_generation import reference_manifest,verified_reference
from fastapi.testclient import TestClient
assert api.index.app is api.main.app
references=[r.id for r in reference_manifest().images]
for module in (api.index,api.main):
 assert Path(module.__file__).resolve().is_relative_to(Path(sys.argv[1]))
 client=TestClient(module.app)
 assert client.get('/api/health').status_code==200
 assert client.get('/api/live-design/config').status_code==422
 for room_type in ('bedroom','living-room'):
  response=client.get('/api/live-design/config',params={'roomType':room_type})
  assert response.status_code==200
  assert response.json()['realCallsEnabled'] is False
 assert client.get('/api/captures/config').status_code==200
 assert client.get('/api/saved-designs/config').status_code==200
 assert client.get('/api/catalogue-gallery').status_code==404
 assert not any(getattr(route,'path','')=='/api/catalogue-gallery' for route in module.app.routes)
 assert not any('curator' in str(getattr(route,'path','')) for route in module.app.routes)
 for r in reference_manifest().images:
  data=verified_reference(r)
  assert len(data)==r.bytes and hashlib.sha256(data).hexdigest()==r.sha256
  assert client.get('/style-references/'+r.fileName).content==data
products=[p.model_dump(mode='json') for p in catalogue.list(CatalogueQuery())]
styles={p['id']:catalogue.private_style_ids(p['id']) for p in products}
eligible={room+':'+style:[p.id for p in catalogue.list(CatalogueQuery(room_type=room,private_style_id=style))]
          for room in ('bedroom','living-room') for style in ('style-01','style-02','style-03','style-04','style-05')}
print(json.dumps({'version':catalogue.version,'products':products,'references':references,'styles':styles,'eligible':eligible},sort_keys=True))
'''
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(package_view)], cwd=package_view,
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    expected = [p.model_dump(mode="json") for p in catalogue.list(CatalogueQuery())]
    assert actual["products"] == expected
    assert len(expected) == 315
    assert actual["version"] == catalogue.version
    assert len(actual["references"]) == 6
    assert actual["styles"] == {p["id"]: list(catalogue.private_style_ids(p["id"])) for p in expected}
    assert actual["eligible"] == {
        room + ":" + style: [p.id for p in catalogue.list(CatalogueQuery(room_type=room, private_style_id=style))]
        for room in ("bedroom", "living-room")
        for style in ("style-01", "style-02", "style-03", "style-04", "style-05")
    }


def test_vite_retains_every_exact_published_product_byte(package_view):
    source = ROOT / "public/products"
    destination = ROOT / "dist/products"
    expected = {p.relative_to(source).as_posix(): p for p in source.rglob("*") if p.is_file()}
    actual = {p.relative_to(destination).as_posix(): p for p in destination.rglob("*") if p.is_file()}
    assert set(actual) == set(expected)
    assert len(expected) == 5058
    assert sum(p.stat().st_size for p in expected.values()) == 542883278
    for name, p in expected.items():
        assert hashlib.sha256(actual[name].read_bytes()).digest() == hashlib.sha256(p.read_bytes()).digest(), name
