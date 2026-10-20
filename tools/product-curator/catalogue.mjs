import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { PRODUCT_ASSET_SOURCES } from '../../scripts/asset-pipeline.config.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { digest, python, ownRoot, ownedPath, hashFile } from './safety.mjs';
import { livingProfile, LIVING_PROFILE, LIVING_PURPOSE, AGENT_PURPOSE } from './profiles.mjs';

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
export async function freezeInputs({ profile = 'bedroom20', preparedDir, ownerIdentity, actor = 'owner', reviewerIdentity } = {}) {
  assert(['bedroom20', LIVING_PROFILE].includes(profile), 'Unknown bounded profile');
  if (profile === LIVING_PROFILE) {
    const identity = actor === 'agent' ? reviewerIdentity : ownerIdentity;
    assert(typeof identity === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9 ._-]{2,79}$/.test(identity), 'Explicit review identity required');
    if (actor === 'agent') assert(!ownerIdentity, 'Agent review uses reviewer identity, never owner identity');
    const { raw, seed: proposal, sources } = await livingProfile();
    const seed = await adapter({ mode: 'seed', profile, seed: proposal });
    const referenceRaw = await readFile(path.join(REPO_ROOT, 'api/live-reference-manifest.json'));
    const references = JSON.parse(referenceRaw);
    const reviewImages = [];
    for (const record of references.images) {
      assert(/^ref-0[1-6]\.jpg$/.test(record.fileName), 'Unknown review image path');
      assert.deepEqual(await hashFile(path.join(REPO_ROOT, 'public/style-references', record.fileName)), { bytes: record.bytes, sha256: record.sha256 }, 'Review image identity changed');
      reviewImages.push({ ...record, imageUrl: `/review-images/${record.sha256}/${record.fileName}` });
    }
    assert.equal(reviewImages.length, 6);
    const root = await ownRoot(preparedDir);
    const prepared = JSON.parse(await readFile(await ownedPath(root, 'prepared.json'), 'utf8'));
    assert.equal(prepared.profile, profile);
    assert.equal(prepared.seedSha256, digest(raw), 'Prepared profile changed');
    const previews = {};
    for (const source of sources) {
      const reused = PRODUCT_ASSET_SOURCES.some((s) => s.productId === source.productId);
      const directory = reused ? path.join(REPO_ROOT, 'public/products', source.productId) : await ownedPath(root, 'preparations', source.productId, 'output');
      const sourcePath = reused ? undefined : await ownedPath(root, 'preparations', source.productId, 'source', source.sourceFile);
      const verified = await verifyProductAssets(directory, source, { sourcePath });
      if (!reused) {
        const record = prepared.preparations.find((p) => p.source.productId === source.productId);
        assert(record, 'Missing immutable preparation');
        assert.deepEqual(record.source, source);
        assert.deepEqual(record.files, verified.files, 'Prepared outputs changed');
        assert.deepEqual(await hashFile(await ownedPath(root, 'preparations', source.productId, 'input.json')), record.input, 'Preparation input changed');
      }
      previews[source.productId] = { manifest: verified.manifest, files: verified.files, identity: digest(JSON.stringify(verified.files)), directory };
    }
    assert.equal(prepared.preparations.length, 4);
    return { seedSha256: digest(raw), seedBytes: raw.length, seed, previews, orderedSources: sources, profile, purpose: actor === 'agent' ? AGENT_PURPOSE : LIVING_PURPOSE, ...(actor === 'agent' ? { reviewerIdentity } : { ownerIdentity }), preparedDir: root, reviewImages, referenceManifestSha256: digest(referenceRaw) };
  }
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
  return adapter({ mode: 'project', profile: freeze.profile, seed: freeze.seed, productId: candidate.productId, styles: candidate.styles, rooms: candidate.rooms, manifest, meshBase: `/mesh/attempt/${attempt.id}` });
}
export function catalogue(entries, query = {}) {
  return adapter({ mode: 'catalogue', entries, query });
}
