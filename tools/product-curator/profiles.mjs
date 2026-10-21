import assert from 'node:assert/strict';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { PRODUCT_ASSET_SOURCES } from '../../scripts/asset-pipeline.config.mjs';

export const LIVING_PROFILE = 'living-seed-v1';
export const LIVING_PURPOSE = 'Ticket12 living seed suitability and Style review v1';
export const AGENT_PURPOSE = 'Ticket12 genuine agent living seed suitability and Style review v1';
export const sourceRecord = (p) => ({
  productId: p.productId,
  sourceUrl: `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${p.sourcePath}`,
  sourceFile: `${p.itemId}.glb`, sourceSha256: p.sourceSha256,
  sourceBytes: p.sourceBytes, sourceFrontAxis: '+z',
});
export async function livingProfile() {
  const raw = await readFile(path.join(REPO_ROOT, 'api/catalogue/providers/abo-living-candidates.json'));
  const seed = JSON.parse(raw);
  assert(seed.products.length >= 5 && seed.products.length <= 8);
  const reused = seed.products.filter((p) => PRODUCT_ASSET_SOURCES.some((s) => s.productId === p.productId));
  assert.equal(reused.length, 4);
  for (const p of reused) assert.deepEqual(sourceRecord(p), PRODUCT_ASSET_SOURCES.find((s) => s.productId === p.productId));
  assert.equal(seed.products.length - reused.length, 4);
  return { raw, seed, sources: seed.products.map(sourceRecord) };
}
