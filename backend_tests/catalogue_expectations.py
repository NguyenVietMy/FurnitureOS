"""Independent exact identities: frozen legacy20 plus the explicit reviewed subset."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def expected_expansion():
    index=ROOT/'api/catalogue/providers/expansion/index.json'
    if not index.exists():return [],None
    index=json.loads(index.read_bytes());entries=[]
    assert index['schemaVersion']==1 and index['policyVersion']=='catalogue-expansion-index-v1'
    for digest in index['batches']:
        assert len(digest)==64 and all(c in '0123456789abcdef' for c in digest)
        raw=(ROOT/f'api/catalogue/providers/expansion/{digest}.json').read_bytes()
        assert hashlib.sha256(raw).hexdigest()==digest
        entries.extend(json.loads(raw)['entries'])
    assert len({e['record']['productId'] for e in entries})==len(entries)
    version=index['baseVersion']+'+expansion-'+hashlib.sha256(json.dumps(index,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return entries,version


def expected_publication():
    frozen = json.loads((ROOT/'tests/fixtures/catalogue-identities.json').read_text())
    # Legacy metadata already has a text Git contract; bind its exact content
    # while allowing the existing checkout EOL conversion. Living pins stay raw.
    assert hashlib.sha256((ROOT/'api/catalogue/providers/abo-seed.json').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == frozen['legacySeedLfSha256']
    legacy = set(frozen['legacyIds'])
    assert len(legacy) == 20
    reviewed = ROOT/'api/catalogue/providers/abo-living-reviewed.json'
    if not reviewed.exists():
        return legacy, set(), frozen['legacyVersion']
    raw = reviewed.read_bytes()
    evidence = json.loads(raw)
    assert evidence['version'] == 'abo-living-reviewed-v1'
    assert evidence['reviewActor'] in ('agent', 'owner')
    living = {row['productId'] for row in evidence['entries']}
    assert len(living) == len(evidence['entries'])
    assert living <= set(frozen['authorizedNewIds']+frozen['authorizedReusedIds'])
    base=frozen['legacyVersion']+'+living-'+hashlib.sha256(raw).hexdigest()[:16]
    entries,version=expected_expansion()
    if version:assert version.startswith(base+'+expansion-')
    assert not {e['record']['productId'] for e in entries} & (legacy|living)
    return legacy,living,version or base
