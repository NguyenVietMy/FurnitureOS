import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

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
