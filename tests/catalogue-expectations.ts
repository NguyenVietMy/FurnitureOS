import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

function expanded(root: URL, ids: string[], version: string) {
  const indexPath = new URL('api/catalogue/providers/expansion/index.json',root);
  if (!existsSync(indexPath)) return {ids:[...ids].sort(),version};
  const index = JSON.parse(readFileSync(indexPath,'utf8')) as {schemaVersion:number;policyVersion:string;baseVersion:string;batches:string[]};
  assert.equal(index.baseVersion,version); assert.equal(index.schemaVersion,1); assert.equal(index.policyVersion,'catalogue-expansion-index-v1');
  for (const digest of index.batches) {
    assert(/^[a-f0-9]{64}$/.test(digest));
    const raw = readFileSync(new URL(`api/catalogue/providers/expansion/${digest}.json`,root));
    assert.equal(createHash('sha256').update(raw).digest('hex'),digest);
    const batch = JSON.parse(raw.toString()) as {entries:{record:{productId:string}}[]};
    for (const e of batch.entries) {assert(!ids.includes(e.record.productId));ids.push(e.record.productId);}
  }
  const canonicalIndex = JSON.stringify({baseVersion:index.baseVersion,batches:index.batches,policyVersion:index.policyVersion,schemaVersion:index.schemaVersion});
  return {ids:ids.sort(),version:`${version}+expansion-${createHash('sha256').update(canonicalIndex).digest('hex')}`};
}

export function expectedPublication() {
  const root = new URL('../', import.meta.url);
  const frozen = JSON.parse(readFileSync(new URL('tests/fixtures/catalogue-identities.json', root), 'utf8')) as {
    legacySeedLfSha256: string; legacyVersion: string; legacyIds: string[]; authorizedNewIds: string[]; authorizedReusedIds: string[];
  };
  assert.equal(createHash('sha256').update(readFileSync(new URL('api/catalogue/providers/abo-seed.json', root), 'utf8').replaceAll('\r\n', '\n')).digest('hex'), frozen.legacySeedLfSha256);
  assert.equal(new Set(frozen.legacyIds).size, 20);
  const path = fileURLToPath(new URL('api/catalogue/providers/abo-living-reviewed.json', root));
  if (!existsSync(path)) return expanded(root,[...frozen.legacyIds],frozen.legacyVersion);
  const raw = readFileSync(path), reviewed = JSON.parse(raw.toString()) as { version: string; reviewActor: string; entries: { productId: string }[] };
  assert.equal(reviewed.version, 'abo-living-reviewed-v1');
  assert(['owner', 'agent'].includes(reviewed.reviewActor));
  const accepted = reviewed.entries.map((e) => e.productId);
  assert.equal(new Set(accepted).size, accepted.length);
  assert(accepted.every((id) => [...frozen.authorizedNewIds, ...frozen.authorizedReusedIds].includes(id)));
  return expanded(root,[...new Set([...frozen.legacyIds,...accepted])],`${frozen.legacyVersion}+living-${createHash('sha256').update(raw).digest('hex').slice(0,16)}`);
}
