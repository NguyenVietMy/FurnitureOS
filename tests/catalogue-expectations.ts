import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export function expectedPublication() {
  const root = new URL('../', import.meta.url);
  const frozen = JSON.parse(readFileSync(new URL('tests/fixtures/catalogue-identities.json', root), 'utf8')) as {
    legacySeedLfSha256: string; legacyVersion: string; legacyIds: string[]; authorizedNewIds: string[]; authorizedReusedIds: string[];
  };
  assert.equal(createHash('sha256').update(readFileSync(new URL('api/catalogue/providers/abo-seed.json', root), 'utf8').replaceAll('\r\n', '\n')).digest('hex'), frozen.legacySeedLfSha256);
  assert.equal(new Set(frozen.legacyIds).size, 20);
  const path = fileURLToPath(new URL('api/catalogue/providers/abo-living-reviewed.json', root));
  if (!existsSync(path)) return { ids: [...frozen.legacyIds].sort(), version: frozen.legacyVersion };
  const raw = readFileSync(path), reviewed = JSON.parse(raw.toString()) as { version: string; reviewActor: string; entries: { productId: string }[] };
  assert.equal(reviewed.version, 'abo-living-reviewed-v1');
  assert(['owner', 'agent'].includes(reviewed.reviewActor));
  const accepted = reviewed.entries.map((e) => e.productId);
  assert.equal(new Set(accepted).size, accepted.length);
  assert(accepted.every((id) => [...frozen.authorizedNewIds, ...frozen.authorizedReusedIds].includes(id)));
  return { ids: [...new Set([...frozen.legacyIds, ...accepted])].sort(), version: `${frozen.legacyVersion}+living-${createHash('sha256').update(raw).digest('hex').slice(0, 16)}` };
}
