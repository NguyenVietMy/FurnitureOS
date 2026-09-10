import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { assertManifestMeasurement, assertNormalizedBounds } from '../scripts/lib/asset-validation.mjs';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
const publicDir = join(repoRoot, 'public');
const productsDir = join(publicDir, 'products');
const seed = JSON.parse(readFileSync(join(repoRoot, 'api/catalogue/providers/abo-seed.json'), 'utf8')) as {
  products: { productId: string; sourceSha256: string; sourceBytes: number }[];
};
const BUDGET_BYTES = 5_000_000;
const KTX2_IDENTIFIER = [0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a];

interface AssetManifest {
  productId: string;
  source: { sha256: string; bytes: number };
  budget: { limitBytes: number; totalCompressedBytes: number; sharedBytes: number };
  normalization: { frontAxis: string; bounds: { min: number[]; max: number[]; size: number[] } };
  lods: {
    level: number;
    url: string;
    exclusiveBytes: number;
    triangles: number;
    textureMaxPx: number;
    files: string[];
    bounds: { min: number[]; max: number[]; size: number[] };
  }[];
  sharedTextures: { file: string; bytes: number; width: number; height: number }[];
}

interface GltfDocument {
  extensionsRequired?: string[];
  images?: { uri?: string }[];
  textures?: { source?: number; extensions?: Record<string, unknown> }[];
  bufferViews?: { extensions?: Record<string, unknown> }[];
  buffers?: { uri?: string; byteLength: number }[];
}

function ktx2Header(file: string) {
  const buffer = readFileSync(file);
  return {
    identifierOk: [...buffer.subarray(0, 12)].every((byte, index) => byte === KTX2_IDENTIFIER[index]),
    vkFormat: buffer.readUInt32LE(12),
    width: buffer.readUInt32LE(20),
    height: buffer.readUInt32LE(24),
    faceCount: buffer.readUInt32LE(36),
    levelCount: buffer.readUInt32LE(40),
    supercompressionScheme: buffer.readUInt32LE(44),
  };
}

describe('the published Catalogue assets', () => {
  it('contains exactly the 20 curated Product directories', () => {
    const published = readdirSync(productsDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
    expect(published).toEqual(seed.products.map((product) => product.productId).sort());
  });

  for (const record of seed.products) {
    describe(record.productId, () => {
      const productDir = join(productsDir, record.productId);
      const manifest = JSON.parse(readFileSync(join(productDir, 'asset-manifest.json'), 'utf8')) as AssetManifest;
      const readLod = (level: number) => JSON.parse(
        readFileSync(join(productDir, `lod${level}.gltf`), 'utf8'),
      ) as GltfDocument;

      it('pins source identity and normalized publication metadata', () => {
        expect(manifest.productId).toBe(record.productId);
        expect(manifest.source.sha256).toBe(record.sourceSha256);
        expect(manifest.source.bytes).toBe(record.sourceBytes);
        expect(manifest.normalization.frontAxis).toBe('+z');
        expect(manifest.normalization.bounds.min[1]).toBeCloseTo(0, 8);
        expect(manifest.normalization.bounds.min[0]! + manifest.normalization.bounds.max[0]!).toBeCloseTo(0, 3);
        expect(manifest.normalization.bounds.min[2]! + manifest.normalization.bounds.max[2]!).toBeCloseTo(0, 3);
      });

      it('publishes decreasing meshopt/BasisU LODs with progressive texture caps', () => {
        expect(manifest.lods.map((lod) => lod.level)).toEqual([0, 1, 2]);
        expect(manifest.lods.map((lod) => lod.textureMaxPx)).toEqual([2048, 1024, 512]);
        expect(manifest.lods[0]!.triangles).toBeGreaterThan(manifest.lods[1]!.triangles);
        expect(manifest.lods[1]!.triangles).toBeGreaterThan(manifest.lods[2]!.triangles);
        expect(manifest.lods[0]!.exclusiveBytes).toBeGreaterThan(manifest.lods[1]!.exclusiveBytes);
        expect(manifest.lods[1]!.exclusiveBytes).toBeGreaterThan(manifest.lods[2]!.exclusiveBytes);
        for (const lod of manifest.lods) {
          const gltf = readLod(lod.level);
          expect(gltf.extensionsRequired).toEqual(expect.arrayContaining([
            'EXT_meshopt_compression', 'KHR_mesh_quantization', 'KHR_texture_basisu',
          ]));
          for (const view of gltf.bufferViews ?? []) {
            expect(Object.keys(view.extensions ?? {})).toContain('EXT_meshopt_compression');
          }
          for (const image of gltf.images ?? []) {
            expect(image.uri).toMatch(/^textures\/.+\.ktx2$/);
            const header = ktx2Header(join(productDir, image.uri!));
            expect(header.width).toBeLessThanOrEqual(lod.textureMaxPx);
            expect(header.height).toBeLessThanOrEqual(lod.textureMaxPx);
          }
          for (const texture of gltf.textures ?? []) {
            expect(Object.keys(texture.extensions ?? {})).toContain('KHR_texture_basisu');
            expect(texture.source).toBeUndefined();
          }
        }
      });

      it('remeasures published bytes with every shared path counted once', () => {
        let exclusive = 0;
        const referencedTextures = new Set<string>();
        for (const lod of manifest.lods) {
          let lodBytes = 0;
          for (const file of lod.files) {
            expect(existsSync(join(productDir, file))).toBe(true);
            lodBytes += statSync(join(productDir, file)).size;
          }
          expect(lodBytes).toBe(lod.exclusiveBytes);
          exclusive += lodBytes;
          for (const image of readLod(lod.level).images ?? []) referencedTextures.add(image.uri!);
        }
        expect([...referencedTextures].sort()).toEqual(manifest.sharedTextures.map((texture) => texture.file).sort());
        let shared = 0;
        for (const file of referencedTextures) shared += statSync(join(productDir, file)).size;
        const total = exclusive + shared;
        expect(shared).toBe(manifest.budget.sharedBytes);
        expect(total).toBe(manifest.budget.totalCompressedBytes);
        expect(manifest.budget.limitBytes).toBe(BUDGET_BYTES);
        expect(total).toBeLessThan(BUDGET_BYTES);
      });

      it('ships valid BasisLZ KTX2 mip chains', () => {
        for (const texture of manifest.sharedTextures) {
          const path = join(productDir, texture.file);
          const header = ktx2Header(path);
          expect(statSync(path).size).toBe(texture.bytes);
          expect(header.identifierOk).toBe(true);
          expect(header.vkFormat).toBe(0);
          expect(header.supercompressionScheme).toBe(1);
          expect(header.faceCount).toBe(1);
          expect(header.levelCount).toBeGreaterThan(1);
          expect(header.width).toBe(texture.width);
          expect(header.height).toBe(texture.height);
        }
      });
    });
  }

  it('serves the BasisU transcoder from this origin', () => {
    for (const file of ['basis_transcoder.js', 'basis_transcoder.wasm']) {
      const path = join(publicDir, 'decoders', 'basis', file);
      expect(existsSync(path)).toBe(true);
      expect(statSync(path).size).toBeGreaterThan(1024);
    }
  });

  it('rejects measured geometry that drifts outside the floor-centre frame', () => {
    expect(() => assertNormalizedBounds('drift fixture', {
      min: [-1, 0.003, -2],
      max: [1, 1, 2],
    })).toThrow(/floor-centre normalization/);
  });

  it('rejects measured triangle and bounds drift from a manifest LOD', () => {
    const declared = {
      triangles: 12,
      bounds: { min: [-1, 0, -2], max: [1, 1, 2], size: [2, 1, 4] },
    };
    const measured = {
      triangles: 11,
      min: [-1, 0, -2],
      max: [1, 1, 2],
      size: [2, 1, 4],
    };
    expect(() => assertManifestMeasurement('triangle fixture', declared, measured)).toThrow(/triangles/);
    expect(() => assertManifestMeasurement('bounds fixture', declared, {
      ...measured,
      triangles: 12,
      max: [1.01, 1, 2],
    })).toThrow(/bounds\.max/);
  });
});
