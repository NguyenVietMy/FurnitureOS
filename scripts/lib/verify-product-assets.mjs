// Reopens bytes independently of the builder. Both the default report and local
// curator use this authority; no converter exit code constitutes validation.
import assert from 'node:assert/strict';
import { lstat, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { measureGltf } from './gltf-measure.mjs';
import { ktx2Info } from './ktx2-info.mjs';
import { assertManifestMeasurement, assertNormalizedBounds, normalizationTranslation, maxBoundsDelta, NORMALIZATION_TOLERANCE_M } from './asset-validation.mjs';

function keys(value, required, optional = []) {
  assert(value && typeof value === 'object' && !Array.isArray(value), 'Expected an object');
  assert(required.every((key) => Object.hasOwn(value, key)), `Missing required fields: ${required}`);
  assert(Object.keys(value).every((key) => [...required, ...optional].includes(key)), 'Unknown manifest field');
}
function finite(value) {
  if (typeof value === 'number') assert(Number.isFinite(value), 'Nonfinite manifest number');
  if (value && typeof value === 'object') Object.values(value).forEach(finite);
}
function bounds(value) {
  keys(value, ['min', 'max', 'size']);
  for (const field of ['min', 'max', 'size']) {
    assert(Array.isArray(value[field]) && value[field].length === 3 && value[field].every(Number.isFinite), 'Invalid bounds');
  }
  value.size.forEach((size, i) => {
    assert(size > 0 && Math.abs(value.max[i] - value.min[i] - size) < 0.000003, 'Invalid bounds size');
  });
}
export function safeAssetPath(file) {
  assert(typeof file === 'string' && /^(?:textures\/[a-zA-Z0-9_.-]+\.ktx2|lod[012]\.(?:bin|gltf)|asset-manifest\.json)$/.test(file), `Unsafe asset path: ${file}`);
  return file;
}
export async function assetBytes(dir, file) {
  safeAssetPath(file);
  let current = path.resolve(dir);
  assert(!(await lstat(current)).isSymbolicLink(), 'Linked output directory');
  for (const part of file.split('/')) {
    current = path.join(current, part);
    assert(!(await lstat(current)).isSymbolicLink(), 'Linked asset');
  }
  assert((await lstat(current)).isFile(), 'Asset must be a regular file');
  return readFile(current);
}
export async function verifyProductAssets(dir, expected, { sourcePath } = {}) {
  const manifest = JSON.parse(await assetBytes(dir, 'asset-manifest.json'));
  finite(manifest);
  keys(manifest, ['productId', 'generatedBy', 'source', 'normalization', 'budget', 'sharedTextures', 'lods']);
  assert.equal(manifest.productId, expected.productId, 'Product identity mismatch');
  assert.equal(manifest.generatedBy, 'scripts/build-product-assets.mjs');
  keys(manifest.source, ['url', 'sha256', 'bytes', 'bounds', 'triangles']);
  assert.equal(manifest.source.sha256, expected.sourceSha256, 'Source identity mismatch');
  assert.equal(manifest.source.bytes, expected.sourceBytes, 'Source byte identity mismatch');
  assert.equal(manifest.source.url, expected.sourceUrl, 'Source URL mismatch');
  bounds(manifest.source.bounds);
  assert(Number.isInteger(manifest.source.triangles) && manifest.source.triangles > 0, 'Invalid source triangle measurement');
  if (sourcePath) {
    const raw = await readFile(sourcePath);
    assert.equal(raw.length, expected.sourceBytes, 'Raw source bytes mismatch');
    assert.equal(createHash('sha256').update(raw).digest('hex'), expected.sourceSha256, 'Raw source hash mismatch');
    const measured = await measureGltf(sourcePath);
    finite(measured);
    assertManifestMeasurement('source', manifest.source, measured);
  }
  const n = manifest.normalization;
  keys(n, ['unit', 'upAxis', 'frontAxis', 'originRule', 'bounds', 'appliedTransform', 'note']);
  assert.deepEqual([n.unit, n.upAxis, n.frontAxis, n.originRule], ['m', '+y', '+z', 'floor-centre']);
  keys(n.appliedTransform, ['translation', 'rotationYaw', 'scale']);
  assert.equal(n.appliedTransform.scale, 1);
  assert.equal(n.appliedTransform.rotationYaw, 0);
  assert.equal(typeof n.note, 'string');
  bounds(n.bounds);
  assert.deepEqual(n.bounds.size, manifest.source.bounds.size, 'Source dimensions must be preserved');
  const translation = normalizationTranslation(manifest.source.bounds);
  assert(Array.isArray(n.appliedTransform.translation) && n.appliedTransform.translation.length === 3);
  translation.forEach((v, i) => assert(Math.abs(v - n.appliedTransform.translation[i]) < 0.000002, 'Normalization translation mismatch'));
  for (const field of ['min', 'max']) n.bounds[field].forEach((v, i) => assert(Math.abs(v - manifest.source.bounds[field][i] - translation[i]) < 0.000003, 'Normalized bounds mismatch'));
  assertNormalizedBounds('manifest', n.bounds);
  keys(manifest.budget, ['limitBytes', 'totalCompressedBytes', 'sharedBytes']);
  assert.equal(manifest.budget.limitBytes, 5_000_000);
  assert.deepEqual(manifest.lods.map((l) => l.level), [0, 1, 2], 'Ordered three LODs required');
  assert.deepEqual(manifest.lods.map((l) => l.textureMaxPx), [2048, 1024, 512]);
  const files = new Set(['asset-manifest.json']);
  const referencedTextures = new Set();
  let exclusive = 0;
  let priorTriangles = Infinity;
  for (const lod of manifest.lods) {
    keys(lod, ['level', 'url', 'simplifyRatio', 'textureMaxPx', 'triangles', 'vertices', 'files', 'exclusiveBytes', 'bounds', 'extensionsRequired'], ['postSimplificationNormalization']);
    bounds(lod.bounds);
    assert.equal(lod.url, `/products/${expected.productId}/lod${lod.level}.gltf`);
    assert.equal(lod.simplifyRatio, [1, 0.4, 0.12][lod.level]);
    assert(Number.isInteger(lod.triangles) && lod.triangles > 0 && lod.triangles < priorTriangles, 'LOD triangle order');
    priorTriangles = lod.triangles;
    if (lod.postSimplificationNormalization) {
      const p = lod.postSimplificationNormalization;
      keys(p, ['translation', 'maxAbsTranslationM', 'maxBoundsDeltaFromLod0M']);
      assert(Array.isArray(p.translation) && p.translation.length === 3 && p.translation.every(Number.isFinite));
      assert.equal(p.maxAbsTranslationM, Math.max(...p.translation.map(Math.abs)));
      assert(Math.abs(p.maxBoundsDeltaFromLod0M - (lod.level ? maxBoundsDelta(lod.bounds, manifest.lods[0].bounds) : 0)) < 0.000001, 'Post-simplification bounds evidence mismatch');
    }
    const gltf = JSON.parse(await assetBytes(dir, `lod${lod.level}.gltf`));
    assert(gltf.asset?.version === '2.0', 'glTF 2.0 required');
    for (const buffer of gltf.buffers ?? []) {
      if (!buffer.uri) assert(buffer.extensions?.EXT_meshopt_compression?.fallback === true, 'URI-less non-fallback buffer');
    }
    const buffers = (gltf.buffers ?? []).filter((b) => b.uri).map((b) => safeAssetPath(b.uri));
    const images = (gltf.images ?? []).map((i) => safeAssetPath(i.uri));
    assert(buffers.length > 0 && images.length > 0, 'External buffers and BasisU textures required');
    assert.deepEqual([...lod.files].sort(), [`lod${lod.level}.gltf`, ...new Set(buffers)].sort(), 'LOD file union mismatch');
    for (const file of [...buffers, ...images]) await assetBytes(dir, file); // contain before NodeIO reads
    const measured = await measureGltf(path.join(dir, `lod${lod.level}.gltf`));
    finite(measured);
    assertManifestMeasurement(`lod${lod.level}`, lod, measured);
    assertNormalizedBounds(`lod${lod.level}`, measured);
    if (lod.level === 0) {
      // simplifyRatio=1 preserves the canonical source's full triangle count;
      // self-consistent reduced topology must not masquerade as full LOD0.
      assert.equal(measured.triangles, manifest.source.triangles, 'LOD0 must preserve canonical source triangle count');
      // Product dimensions use these canonical source bounds, so matching a
      // regenerated per-LOD manifest alone cannot establish preserved scale.
      // LOD0 keeps full geometry but uses 16-bit position quantization; measures
      // round to 1e-6 m. Reuse the existing 0.002 m normalization tolerance for
      // this source-to-published comparison, rather than the 1e-6 m tolerance
      // for remeasuring the same published bytes. Check size as well as extrema.
      for (const field of ['min', 'max', 'size']) measured[field].forEach((value, axis) => {
        assert(Math.abs(value - n.bounds[field][axis]) <= NORMALIZATION_TOLERANCE_M,
          `lod0 measured bounds ${field}[${axis}] ${value} differs from canonical normalized source ${n.bounds[field][axis]} beyond ${NORMALIZATION_TOLERANCE_M} m`);
      });
    }
    assert.equal(measured.vertices, lod.vertices);
    assert.deepEqual(measured.extensionsRequired, [...lod.extensionsRequired].sort());
    for (const ext of ['EXT_meshopt_compression', 'KHR_texture_basisu']) assert(measured.extensionsRequired.includes(ext), `Missing ${ext}`);
    let bytes = 0;
    for (const file of lod.files) {
      assert(!files.has(file), 'Duplicate exclusive file');
      files.add(file);
      bytes += (await assetBytes(dir, file)).length;
    }
    assert.equal(bytes, lod.exclusiveBytes, 'Exclusive byte mismatch');
    exclusive += bytes;
    for (const texture of measured.textures) {
      assert.equal(texture.mimeType, 'image/ktx2');
      assert(texture.width > 0 && texture.height > 0 && Math.max(texture.width, texture.height) <= lod.textureMaxPx, 'LOD texture cap');
      referencedTextures.add(texture.uri);
    }
  }
  assert.deepEqual([...referencedTextures].sort(), manifest.sharedTextures.map((t) => t.file).sort(), 'Texture union mismatch');
  let shared = 0;
  for (const texture of manifest.sharedTextures) {
    keys(texture, ['file', 'bytes', 'vkFormat', 'width', 'height', 'faceCount', 'levelCount', 'supercompressionScheme', 'supercompression']);
    assert(!files.has(texture.file), 'Duplicate texture');
    files.add(texture.file);
    const info = await ktx2Info(path.join(dir, safeAssetPath(texture.file)));
    assert.deepEqual(info, Object.fromEntries(Object.entries(texture).filter(([key]) => key !== 'file')), 'KTX2 header mismatch');
    assert.equal(info.vkFormat, 0);
    assert.equal(info.faceCount, 1);
    assert.equal(info.supercompression, 'BasisLZ');
    assert.equal(info.levelCount, Math.floor(Math.log2(Math.max(info.width, info.height))) + 1, 'Missing mip chain');
    const bytes = await assetBytes(dir, texture.file);
    assert(bytes.length >= 80 + info.levelCount * 24, 'Truncated KTX2 mip index');
    const ranges = [];
    for (let level = 0; level < info.levelCount; level++) {
      const offset = bytes.readBigUInt64LE(80 + level * 24), length = bytes.readBigUInt64LE(88 + level * 24);
      assert(offset >= BigInt(80 + info.levelCount * 24) && length > 0n && offset + length <= BigInt(bytes.length), 'Invalid KTX2 mip payload range');
      assert(!ranges.some(([start, end]) => offset < end && offset + length > start), 'Overlapping KTX2 mip payloads');
      ranges.push([offset, offset + length]);
    }
    assert(Math.max(info.width, info.height) <= 2048);
    shared += info.bytes;
  }
  const actualFiles = [];
  for (const item of await readdir(dir, { withFileTypes: true })) {
    if (item.name === 'textures' && item.isDirectory()) {
      for (const texture of await readdir(path.join(dir, 'textures'))) actualFiles.push(`textures/${texture}`);
    } else { assert(item.isFile(), 'Unknown output directory/link'); actualFiles.push(item.name); }
  }
  assert.deepEqual(actualFiles.sort(), [...files].sort(), 'Output has missing/extra files');
  assert.equal(shared, manifest.budget.sharedBytes);
  assert.equal(exclusive + shared, manifest.budget.totalCompressedBytes);
  assert(exclusive + shared < 5_000_000, 'Product exceeds strict budget');
  const records = [];
  for (const file of [...files].sort()) {
    const bytes = await assetBytes(dir, file);
    records.push({ file, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
  }
  return { manifest, files: records };
}
