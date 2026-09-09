import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * These tests read the published files, not the manifest's word for them. If
 * `npm run assets:build` were ever skipped, or produced uncompressed geometry,
 * or blew the budget, this is where it shows up.
 */

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
const publicDir = join(repoRoot, 'public');
const PRODUCT_ID = 'bed-prudence-tufted-queen-natural';
const productDir = join(publicDir, 'products', PRODUCT_ID);

interface AssetManifest {
  productId: string;
  budget: { limitBytes: number; totalCompressedBytes: number };
  normalization: { frontAxis: string };
  lods: { level: number; url: string; exclusiveBytes: number }[];
  sharedTextures: { file: string }[];
}

const manifest = JSON.parse(
  readFileSync(join(productDir, 'asset-manifest.json'), 'utf8'),
) as AssetManifest;

const MAX_TEXTURE_PX = 2048;
const ACCEPTED_TOTAL_BYTES = 1_298_091;
const KTX2_IDENTIFIER = [0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a];

/** Reads the fixed-size KTX2 header. Field offsets are from the KTX 2.0 spec. */
function ktx2Header(file: string) {
  const buffer = readFileSync(file);
  const identifier = [...buffer.subarray(0, 12)];
  return {
    identifierOk: identifier.every((byte, index) => byte === KTX2_IDENTIFIER[index]),
    vkFormat: buffer.readUInt32LE(12),
    width: buffer.readUInt32LE(20),
    height: buffer.readUInt32LE(24),
    faceCount: buffer.readUInt32LE(36),
    levelCount: buffer.readUInt32LE(40),
    supercompressionScheme: buffer.readUInt32LE(44),
  };
}

interface GltfImage {
  uri?: string;
}

interface GltfTexture {
  source?: number;
  extensions?: Record<string, unknown>;
}

interface GltfDocument {
  extensionsRequired?: string[];
  images?: GltfImage[];
  textures?: GltfTexture[];
  bufferViews?: { extensions?: Record<string, unknown> }[];
  buffers?: { uri?: string; byteLength: number }[];
}

function readLod(level: number): GltfDocument {
  return JSON.parse(readFileSync(join(productDir, `lod${level}.gltf`), 'utf8')) as GltfDocument;
}

function publicPath(url: string): string {
  return join(publicDir, url.replace(/^\//, ''));
}

function sharedTextureUrls(): string[] {
  return manifest.sharedTextures.map(({ file }) => `/products/${manifest.productId}/${file}`);
}

describe('the published Product assets', () => {
  it('publishes every file the manifest promises', () => {
    expect(manifest.productId).toBe(PRODUCT_ID);
    expect(manifest.normalization.frontAxis).toBe('+z');
    for (const lod of manifest.lods) expect(existsSync(publicPath(lod.url))).toBe(true);
    for (const url of sharedTextureUrls()) expect(existsSync(publicPath(url))).toBe(true);
  });

  it.each([0, 1, 2])('compresses LOD %i with meshopt, quantization and BasisU', (level) => {
    const gltf = readLod(level);
    expect(gltf.extensionsRequired).toContain('EXT_meshopt_compression');
    expect(gltf.extensionsRequired).toContain('KHR_mesh_quantization');
    expect(gltf.extensionsRequired).toContain('KHR_texture_basisu');

    const views = gltf.bufferViews ?? [];
    expect(views.length).toBeGreaterThan(0);
    for (const view of views) {
      expect(Object.keys(view.extensions ?? {})).toContain('EXT_meshopt_compression');
    }
  });

  it('shares one set of external KTX2 textures across all three levels', () => {
    const uriSets = [0, 1, 2].map((level) =>
      (readLod(level).images ?? []).map((image) => image.uri ?? '').sort(),
    );
    expect(uriSets[0]!.length).toBeGreaterThan(0);
    expect(uriSets[0]).toEqual(manifest.sharedTextures.map(({ file }) => file).sort());
    expect(uriSets[1]).toEqual(uriSets[0]);
    expect(uriSets[2]).toEqual(uriSets[0]);
    for (const image of readLod(0).images ?? []) expect(image.uri).toMatch(/^textures\/.+\.ktx2$/);
    for (const texture of readLod(0).textures ?? []) {
      expect(Object.keys(texture.extensions ?? {})).toContain('KHR_texture_basisu');
      expect(texture.source).toBeUndefined();
    }
  });

  it('caps textures at 2048 px and ships BasisLZ mip chains', () => {
    for (const url of sharedTextureUrls()) {
      const header = ktx2Header(publicPath(url));
      expect(header.identifierOk).toBe(true);
      expect(header.vkFormat).toBe(0);
      expect(header.supercompressionScheme).toBe(1);
      expect(header.faceCount).toBe(1);
      expect(header.width).toBeLessThanOrEqual(MAX_TEXTURE_PX);
      expect(header.height).toBeLessThanOrEqual(MAX_TEXTURE_PX);
      expect(header.levelCount).toBeGreaterThan(1);
    }
  });

  it('measures the accepted aggregate bytes with referenced buffers and shared files counted once', () => {
    let geometry = 0;
    for (const level of [0, 1, 2]) {
      geometry += statSync(join(productDir, `lod${level}.gltf`)).size;
      const buffers = readLod(level).buffers ?? [];
      expect(buffers.length).toBeGreaterThan(0);
      let referencedBuffers = 0;
      for (const buffer of buffers) {
        if (buffer.uri) {
          referencedBuffers += 1;
          geometry += statSync(join(productDir, buffer.uri)).size;
        }
      }
      expect(referencedBuffers).toBeGreaterThan(0);
    }
    const textures = new Set(sharedTextureUrls());
    const total = geometry + [...textures].reduce((sum, url) => sum + statSync(publicPath(url)).size, 0);

    expect(total).toBe(ACCEPTED_TOTAL_BYTES);
    expect(total).toBeLessThan(manifest.budget.limitBytes);
    expect(manifest.budget.totalCompressedBytes).toBe(total);
    const [lod0, lod1, lod2] = manifest.lods;
    expect(lod0!.exclusiveBytes).toBeGreaterThan(lod1!.exclusiveBytes);
    expect(lod1!.exclusiveBytes).toBeGreaterThan(lod2!.exclusiveBytes);
  });

  it('serves the BasisU transcoder from this origin, not a third-party CDN', () => {
    for (const file of ['basis_transcoder.js', 'basis_transcoder.wasm']) {
      const path = join(publicDir, 'decoders', 'basis', file);
      expect(existsSync(path)).toBe(true);
      expect(statSync(path).size).toBeGreaterThan(1024);
    }
  });
});
