/**
 * Product asset pipeline.
 *
 * Upstream glTF -> three LODs of meshopt-compressed geometry that share one set
 * of KTX2 textures, written into `public/products/<productId>/` together with an
 * `asset-manifest.json` recording exactly what was produced and what it weighs.
 *
 * The pipeline never scales geometry. Upstream models are already metric, +Y up,
 * +Z front and resting on the Y=0 plane, so normalization is an identity
 * transform whose *measured* result is recorded as evidence. The Catalogue
 * declares dimensions that are then checked against the shipped file rather
 * than typed in by hand.
 *
 *   node scripts/build-product-assets.mjs
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { copyFile, mkdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { NodeIO } from '@gltf-transform/core';
import {
  ASSET_BUDGET_BYTES,
  CANONICAL_FRONT_AXIS,
  LOD_LEVELS,
  MAX_TEXTURE_PX,
  PRODUCT_ASSET_SOURCES,
} from './asset-pipeline.config.mjs';
import { ensureGltfpack, sha256File } from './lib/ensure-gltfpack.mjs';
import { measureGltf } from './lib/gltf-measure.mjs';
import { ktx2Info } from './lib/ktx2-info.mjs';
import { repoPath } from './lib/paths.mjs';

const SOURCE_DIR = repoPath('assets', 'source');
const WORK_DIR = repoPath('assets', 'work');

async function ensureSource({ sourceUrl, sourceFile, sourceSha256 }) {
  const target = path.join(SOURCE_DIR, sourceFile);
  if (!existsSync(target)) {
    console.log(`  downloading ${sourceUrl}`);
    const res = await fetch(sourceUrl);
    if (!res.ok) throw new Error(`Failed to download ${sourceUrl}: HTTP ${res.status}`);
    await mkdir(SOURCE_DIR, { recursive: true });
    await writeFile(target, Buffer.from(await res.arrayBuffer()));
  }
  const digest = await sha256File(target);
  if (digest !== sourceSha256) {
    throw new Error(
      `Checksum mismatch for ${sourceFile}: expected ${sourceSha256}, got ${digest}. ` +
        'The upstream asset changed; re-curate before shipping it.',
    );
  }
  return { path: target, sha256: digest, bytes: (await stat(target)).size };
}

/**
 * gltfpack only writes texture files next to its output when the *input*
 * references images as files, so the packed GLB is unpacked first. This is also
 * the only step that reads the upstream file, which keeps the provider's
 * packaging choices out of everything downstream.
 */
async function unpackSource(sourcePath, workDir) {
  const io = new NodeIO();
  const doc = await io.read(sourcePath);
  doc
    .getRoot()
    .listTextures()
    .forEach((texture, index) => {
      const mime = texture.getMimeType();
      const ext = mime === 'image/png' ? 'png' : mime === 'image/jpeg' ? 'jpg' : 'bin';
      texture.setURI(`source-tex${index}.${ext}`);
    });
  const unpacked = path.join(workDir, 'source.gltf');
  await io.write(unpacked, doc);
  return unpacked;
}

async function buildLod(bin, unpackedSource, workDir, lod) {
  const lodDir = path.join(workDir, `lod${lod.level}`);
  await rm(lodDir, { recursive: true, force: true });
  await mkdir(lodDir, { recursive: true });
  const out = path.join(lodDir, `lod${lod.level}.gltf`);
  execFileSync(
    bin,
    [
      '-i', unpackedSource,
      '-o', out,
      '-cc', //                          meshopt compression, higher ratio
      '-tc', //                          KTX2 / BasisU textures
      '-tl', String(MAX_TEXTURE_PX), //  cap the longest texture edge
      '-tq', '8',
      '-si', String(lod.simplifyRatio),
      '-se', String(lod.maxDeviation),
      '-slb', //                         lock border vertices so LODs keep the silhouette
      '-vp', '16', //                    16-bit position quantization (~0.03mm over 2m)
    ],
    { stdio: ['ignore', 'pipe', 'inherit'] },
  );
  return { lodDir, gltfPath: out };
}

async function totalBytes(dir, files) {
  let total = 0;
  for (const file of files) total += (await stat(path.join(dir, file))).size;
  return total;
}

/**
 * Placement derives a Product's back, left and right faces from its yaw alone,
 * which is only correct once the Mesh faces `CANONICAL_FRONT_AXIS`. Rotating a
 * Mesh into that frame is real work — it has to be written and then verified
 * against the asset — so the pipeline refuses to publish a source that needs it
 * rather than shipping a Mesh that would be placed with the wrong side to a wall.
 */
function assertCanonicalSource(product) {
  if (product.sourceFrontAxis !== CANONICAL_FRONT_AXIS) {
    throw new Error(
      `Source for ${product.productId} faces "${product.sourceFrontAxis}", but published Meshes ` +
        `must face "${CANONICAL_FRONT_AXIS}". Add a normalization rotation to this pipeline, ` +
        'record the applied yaw in the manifest, and verify the result against the asset ' +
        'before publishing it.',
    );
  }
}

async function publishProduct(product) {
  console.log(`\n${product.productId}`);
  assertCanonicalSource(product);
  const bin = await ensureGltfpack();
  const source = await ensureSource(product);
  console.log(
    `  source ${path.basename(source.path)} ${source.bytes} bytes sha256:${source.sha256.slice(0, 12)}`,
  );

  const workDir = path.join(WORK_DIR, product.productId);
  await rm(workDir, { recursive: true, force: true });
  await mkdir(workDir, { recursive: true });
  const unpacked = await unpackSource(source.path, workDir);
  const sourceMeasure = await measureGltf(unpacked);

  const outDir = repoPath('public', 'products', product.productId);
  const textureDir = path.join(outDir, 'textures');
  await rm(outDir, { recursive: true, force: true });
  await mkdir(textureDir, { recursive: true });

  /** content hash -> published file name, so every LOD shares one texture copy. */
  const publishedTextures = new Map();
  const lods = [];

  for (const lod of LOD_LEVELS) {
    const { lodDir, gltfPath } = await buildLod(bin, unpacked, workDir, lod);
    const gltf = JSON.parse(await readFile(gltfPath, 'utf8'));

    for (const image of gltf.images ?? []) {
      if (!image.uri) {
        throw new Error(
          `lod${lod.level} embedded image "${image.name}" in its buffer; expected an external file`,
        );
      }
      const bytes = await readFile(path.join(lodDir, image.uri));
      const hash = createHash('sha256').update(bytes).digest('hex');
      let fileName = publishedTextures.get(hash);
      if (!fileName) {
        fileName = `${path.parse(image.uri).name}-${hash.slice(0, 12)}.ktx2`;
        await writeFile(path.join(textureDir, fileName), bytes);
        publishedTextures.set(hash, fileName);
      }
      image.uri = `textures/${fileName}`;
    }

    const buffers = (gltf.buffers ?? []).filter((buffer) => buffer.uri);
    for (const buffer of buffers) {
      await copyFile(path.join(lodDir, buffer.uri), path.join(outDir, buffer.uri));
    }

    const publishedGltf = path.join(outDir, `lod${lod.level}.gltf`);
    await writeFile(publishedGltf, `${JSON.stringify(gltf, null, 1)}\n`);
    const measure = await measureGltf(publishedGltf);

    const files = [path.basename(publishedGltf), ...buffers.map((b) => b.uri)];
    const exclusiveBytes = await totalBytes(outDir, files);
    lods.push({
      level: lod.level,
      url: `/products/${product.productId}/lod${lod.level}.gltf`,
      simplifyRatio: lod.simplifyRatio,
      triangles: measure.triangles,
      vertices: measure.vertices,
      files,
      exclusiveBytes,
      bounds: { min: measure.min, max: measure.max, size: measure.size },
      extensionsRequired: measure.extensionsRequired,
    });
    console.log(`  lod${lod.level}: ${measure.triangles} tris, ${exclusiveBytes} geometry bytes`);
  }

  const textureFiles = [...publishedTextures.values()].sort();
  const sharedBytes = await totalBytes(textureDir, textureFiles);
  const totalCompressedBytes = lods.reduce((sum, l) => sum + l.exclusiveBytes, 0) + sharedBytes;

  const sharedTextures = [];
  for (const file of textureFiles) {
    sharedTextures.push({ file: `textures/${file}`, ...(await ktx2Info(path.join(textureDir, file))) });
  }
  const oversized = sharedTextures.filter(
    (t) => t.width > MAX_TEXTURE_PX || t.height > MAX_TEXTURE_PX,
  );
  if (oversized.length) {
    throw new Error(
      `Textures exceed ${MAX_TEXTURE_PX}px: ${oversized.map((t) => t.file).join(', ')}`,
    );
  }
  if (totalCompressedBytes >= ASSET_BUDGET_BYTES) {
    throw new Error(
      `Product ${product.productId} is ${totalCompressedBytes} bytes, over the ${ASSET_BUDGET_BYTES} byte budget`,
    );
  }

  const manifest = {
    productId: product.productId,
    generatedBy: 'scripts/build-product-assets.mjs',
    source: {
      url: product.sourceUrl,
      sha256: source.sha256,
      bytes: source.bytes,
      bounds: { min: sourceMeasure.min, max: sourceMeasure.max, size: sourceMeasure.size },
      triangles: sourceMeasure.triangles,
    },
    normalization: {
      unit: 'm',
      upAxis: '+y',
      frontAxis: CANONICAL_FRONT_AXIS,
      originRule: 'floor-centre',
      appliedTransform: { translation: [0, 0, 0], rotationYaw: 0, scale: 1 },
      note:
        'The upstream collection guarantees metres, +Y up, +Z front and floor contact at Y=0, ' +
        'so the pipeline applies an identity transform and records measured bounds as evidence ' +
        'that the guarantee held for this Product.',
    },
    budget: { limitBytes: ASSET_BUDGET_BYTES, totalCompressedBytes, sharedBytes },
    sharedTextures,
    lods,
  };
  await writeFile(path.join(outDir, 'asset-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(
    `  textures: ${textureFiles.length} shared files, ${sharedBytes} bytes; ` +
      `total ${totalCompressedBytes} / ${ASSET_BUDGET_BYTES} bytes`,
  );
  return manifest;
}

const manifests = [];
for (const product of PRODUCT_ASSET_SOURCES) manifests.push(await publishProduct(product));
console.log(`\nBuilt ${manifests.length} Product asset set(s).`);
