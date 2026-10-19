import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { PRODUCT_ASSET_SOURCES } from '../../scripts/asset-pipeline.config.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { digest, python } from './safety.mjs';

export function adapter(data) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, [path.join(REPO_ROOT, 'tools/product-curator/abo_adapter.py')], { cwd: REPO_ROOT, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', errors = '';
    child.stdout.on('data', (chunk) => { output += chunk; });
    child.stderr.on('data', (chunk) => { errors += chunk; });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) return reject(new Error(`Pydantic Catalogue validation exit ${code}: ${errors}`));
      try { resolve(JSON.parse(output)); } catch (error) { reject(error); }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify(data));
  });
}
export async function freezeInputs() {
  const raw = await readFile(path.join(REPO_ROOT, 'api/catalogue/providers/abo-seed.json'));
  const seed = await adapter({ mode: 'seed', seed: JSON.parse(raw) });
  assert.equal(seed.products.length, 20, 'Exactly the pinned 20 candidates required');
  assert.deepEqual(seed.products.map((p) => p.productId), PRODUCT_ASSET_SOURCES.map((p) => p.productId), 'Seed changed in running process; restart');
  assert.deepEqual(seed.products.map((p) => ({
    productId: p.productId,
    sourceUrl: `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${p.sourcePath}`,
    sourceFile: `${p.itemId}.glb`, sourceSha256: p.sourceSha256, sourceBytes: p.sourceBytes, sourceFrontAxis: '+z',
  })), PRODUCT_ASSET_SOURCES, 'Source identity changed in running process; restart');
  const previews = {};
  for (const source of PRODUCT_ASSET_SOURCES) {
    const verified = await verifyProductAssets(path.join(REPO_ROOT, 'public/products', source.productId), source);
    previews[source.productId] = { manifest: verified.manifest, files: verified.files, identity: digest(JSON.stringify(verified.files)) };
  }
  return { seedSha256: digest(raw), seedBytes: raw.length, seed, previews, orderedSources: PRODUCT_ASSET_SOURCES };
}
export function project(freeze, candidate, attempt, manifest) {
  return adapter({ mode: 'project', seed: freeze.seed, productId: candidate.productId, styles: candidate.styles, rooms: candidate.rooms, manifest, meshBase: `/mesh/attempt/${attempt.id}` });
}
export function catalogue(entries, query = {}) {
  return adapter({ mode: 'catalogue', entries, query });
}
