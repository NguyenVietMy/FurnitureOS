"""Independent exact identities: frozen legacy20 plus the explicit reviewed subset."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    return legacy, living, frozen['legacyVersion']+'+living-'+hashlib.sha256(raw).hexdigest()[:16]
