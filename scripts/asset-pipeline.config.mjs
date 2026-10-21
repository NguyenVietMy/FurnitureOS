import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { commonAnchorStyles } from './lib/reviewed-anchor-styles.mjs';

/**
 * Declarative input to the Product asset pipeline.
 *
 * Provider-specific curation lives beside the ABO adapter. The pipeline reads
 * that one record and only carries the source URL, checksum and Product id into
 * normalization. This prevents the Catalogue and asset build from drifting.
 */

/** Texture dimensions are capped at this many pixels on the longest edge. */
export const MAX_TEXTURE_PX = 2048;

/**
 * Every published Mesh faces +Z. Placement derives a Product's back, left and
 * right faces from its front axis and its yaw, so a Mesh that faces elsewhere
 * would be placed against a wall by the wrong side. Normalizing here is the
 * narrow alternative to threading a per-Product front axis through the solver,
 * the validator and the scene graph.
 */
export const CANONICAL_FRONT_AXIS = '+z';

/** Compressed bytes allowed per Product, counting each shared file exactly once. */
export const ASSET_BUDGET_BYTES = 5_000_000;

/**
 * Three levels of detail. `simplifyRatio` is a target triangle ratio handed to
 * gltfpack; `maxDeviation` bounds how far the simplified surface may move, in
 * fractions of the mesh extent.
 */
export const LOD_LEVELS = [
  { level: 0, simplifyRatio: 1, maxDeviation: 0.01, textureMaxPx: 2048 },
  { level: 1, simplifyRatio: 0.4, maxDeviation: 0.02, textureMaxPx: 1024 },
  { level: 2, simplifyRatio: 0.12, maxDeviation: 0.05, textureMaxPx: 512 },
];

const seedPath = fileURLToPath(
  new URL('../api/catalogue/providers/abo-seed.json', import.meta.url),
);
export const ABO_SEED = JSON.parse(readFileSync(seedPath, 'utf8'));

export const PRODUCT_ASSET_SOURCES = ABO_SEED.products.map((product) => ({
  productId: product.productId,
  sourceUrl: `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${product.sourcePath}`,
  sourceFile: `${product.itemId}.glb`,
  sourceSha256: product.sourceSha256,
  sourceBytes: product.sourceBytes,
  /** ABO's published coordinate contract is metres, +Y up and +Z front. */
  sourceFrontAxis: '+z',
}));

// The original20 source contract remains exact. Only explicit reviewed metadata
// extends the published union; candidate proposals never do.
const reviewedPath = fileURLToPath(new URL('../api/catalogue/providers/abo-living-reviewed.json', import.meta.url));
export const LIVING_REVIEWED = existsSync(reviewedPath) ? JSON.parse(readFileSync(reviewedPath, 'utf8')) : null;
const proposalBytes = readFileSync(fileURLToPath(new URL('../api/catalogue/providers/abo-living-candidates.json', import.meta.url)));
const proposed = JSON.parse(proposalBytes);
export function validateReviewedLiving(LIVING_REVIEWED) {
  const extra = [];
  assert.equal(LIVING_REVIEWED.version, 'abo-living-reviewed-v1');
  assert.equal(LIVING_REVIEWED.profileSha256, createHash('sha256').update(proposalBytes).digest('hex'));
  assert.deepEqual(Object.keys(LIVING_REVIEWED).sort(), ['schemaVersion','version','profileSha256','reviewActor','reviewEvidenceSha256','entries'].sort());
  assert.equal(LIVING_REVIEWED.schemaVersion, 1);
  assert(['owner', 'agent'].includes(LIVING_REVIEWED.reviewActor));
  assert(/^[a-f0-9]{64}$/.test(LIVING_REVIEWED.reviewEvidenceSha256));
  const categories = new Set();
  const knownStyles = new Set(proposed.styleVocabulary.styles.map((s) => s.id));
  for (const entry of LIVING_REVIEWED.entries) {
    assert.deepEqual(Object.keys(entry).sort(), ['productId','rooms','privateStyleIds','files'].sort());
    assert(entry.files.length >= 8 && entry.files.length <= 64);
    assert.equal(new Set(entry.files.map((f) => f.file)).size, entry.files.length);
    assert(entry.files.some((f) => f.file === 'asset-manifest.json'));
    for (const f of entry.files) {
      assert.deepEqual(Object.keys(f).sort(), ['file','bytes','sha256'].sort());
      assert(/^(?:asset-manifest\.json|lod[012]\.(?:bin|gltf)|textures\/[a-zA-Z0-9_.-]+\.ktx2)$/.test(f.file));
      assert(Number.isSafeInteger(f.bytes) && f.bytes > 0 && /^[a-f0-9]{64}$/.test(f.sha256));
    }
    assert.deepEqual(entry.rooms, ['living-room']);
    assert(entry.privateStyleIds.length && entry.privateStyleIds.length <= 5 && entry.privateStyleIds.every((s) => knownStyles.has(s)));
    assert.equal(new Set(entry.privateStyleIds).size, entry.privateStyleIds.length);
    const p = proposed.products.find((p) => p.productId === entry.productId);
    assert(p, 'Unknown living identity'); categories.add(p.category);
  }
  assert.deepEqual([...categories].sort(), ['chair','lamp','rug','sofa','table']);
  const entries = LIVING_REVIEWED.entries;
  assert(commonAnchorStyles(entries.map((entry) => ({ ...entry, category: proposed.products.find((p) => p.productId === entry.productId).category }))).length, 'All three anchors need a common supported Style');
  assert(LIVING_REVIEWED.entries.length >= 5 && LIVING_REVIEWED.entries.length <= 8);
  const ids = LIVING_REVIEWED.entries.map((e) => e.productId);
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) {
    const p = proposed.products.find((p) => p.productId === id);
    assert(p, 'Unreviewed identity');
    if (!PRODUCT_ASSET_SOURCES.some((s) => s.productId === id)) extra.push({ productId: id, sourceUrl: `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${p.sourcePath}`, sourceFile: `${p.itemId}.glb`, sourceSha256: p.sourceSha256, sourceBytes: p.sourceBytes, sourceFrontAxis: '+z' });
  }
  return extra;
}
const extra = LIVING_REVIEWED ? validateReviewedLiving(LIVING_REVIEWED) : [];
export const PUBLISHED_PRODUCT_ASSET_SOURCES = [...PRODUCT_ASSET_SOURCES, ...extra];

export const PUBLISHED_CATALOGUE_VERSION = LIVING_REVIEWED ? `${ABO_SEED.catalogueVersion}+living-${createHash("sha256").update(readFileSync(reviewedPath)).digest("hex").slice(0,16)}` : ABO_SEED.catalogueVersion;
