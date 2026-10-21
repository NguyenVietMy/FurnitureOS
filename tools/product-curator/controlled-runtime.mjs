// Explicit test fixture export. Never writes a reviewed production overlay.
import assert from 'node:assert/strict';
import { cp } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { PRODUCT_ASSET_SOURCES } from '../../scripts/asset-pipeline.config.mjs';
import { ownRoot, ownedPath } from './safety.mjs';
import { freezeInputs, adapter } from './catalogue.mjs';
import { durableFile } from './store.mjs';
import { copyCandidate } from './runtime-copy.mjs';

const args = process.argv.slice(2);
assert(args.length === 4 && args[0] === '--prepared-dir' && args[2] === '--state-dir');
const root = await ownRoot(args[3]);
const freeze = await freezeInputs({ profile: 'living-seed-v1', preparedDir: args[1], ownerIdentity: 'CONTROLLED-BROWSER-NOT-OWNER' });
const entries = [];
await cp(path.join(REPO_ROOT, 'public/products'), await ownedPath(root, 'public/products'), { recursive: true, force: false, errorOnExist: true });
for (const p of freeze.seed.products) {
  const preview = freeze.previews[p.productId];
  if (!PRODUCT_ASSET_SOURCES.some((s) => s.productId === p.productId)) await copyCandidate(preview, freeze.orderedSources.find((s) => s.productId === p.productId), await ownedPath(root, 'public', 'products', p.productId));
  entries.push(await adapter({ mode: 'project', profile: freeze.profile, seed: freeze.seed, productId: p.productId, styles: ['style-01'], rooms: ['living-room'], manifest: preview.manifest, meshBase: null }));
}
for (const name of ['style-references', 'decoders', 'images']) await cp(path.join(REPO_ROOT, 'public', name), await ownedPath(root, 'public', name), { recursive: true, force: false, errorOnExist: true });
await cp(path.join(REPO_ROOT, 'dist'), await ownedPath(root, 'dist'), { recursive: true, force: false, errorOnExist: true });
await durableFile(await ownedPath(root, 'CONTROLLED-CATALOGUE.json'), { kind: 'CONTROLLED-NOT-OWNER-NOT-PRODUCTION', entries, files: Object.fromEntries(Object.entries(freeze.previews).map(([id, p]) => [id, p.files])) });
console.log(root);
