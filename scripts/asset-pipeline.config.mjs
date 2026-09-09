/**
 * Declarative input to the Product asset pipeline.
 *
 * Everything provider-specific (the ABO S3 layout, the ASIN) lives here and in
 * `src/catalogue/abo/`. The pipeline itself only ever sees a source URL, a
 * checksum and a Product id.
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
export const ASSET_BUDGET_BYTES = 5 * 1024 * 1024;

/**
 * Three levels of detail. `simplifyRatio` is a target triangle ratio handed to
 * gltfpack; `maxDeviation` bounds how far the simplified surface may move, in
 * fractions of the mesh extent.
 */
export const LOD_LEVELS = [
  { level: 0, simplifyRatio: 1, maxDeviation: 0.01 },
  { level: 1, simplifyRatio: 0.4, maxDeviation: 0.02 },
  { level: 2, simplifyRatio: 0.12, maxDeviation: 0.05 },
];

export const PRODUCT_ASSET_SOURCES = [
  {
    productId: 'bed-prudence-tufted-queen-natural',
    sourceUrl:
      'https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/D/B07B4W5T9D.glb',
    sourceFile: 'B07B4W5T9D.glb',
    // sha256 of the upstream file, recorded when the asset was curated.
    sourceSha256: '2513916c1a172e6fdd8e43e8f3f0e570955c19ceeaa59ca6bc0cdb52107ff348',
    /**
     * Which way this upstream Mesh faces, checked when it was curated. The
     * pipeline refuses to publish anything but `CANONICAL_FRONT_AXIS`: rotating
     * a Mesh into the canonical frame is a step that has to be written and
     * verified against a real asset, not assumed, so a Product that needs it
     * fails the build until someone does that work.
     */
    sourceFrontAxis: '+z',
  },
];
