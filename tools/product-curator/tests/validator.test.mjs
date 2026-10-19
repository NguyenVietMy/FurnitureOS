import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, readFile, writeFile, mkdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from '../../../scripts/lib/paths.mjs';
import { PRODUCT_ASSET_SOURCES } from '../../../scripts/asset-pipeline.config.mjs';
import { verifyProductAssets } from '../../../scripts/lib/verify-product-assets.mjs';
import { measureGltf } from '../../../scripts/lib/gltf-measure.mjs';
import { maxBoundsDelta } from '../../../scripts/lib/asset-validation.mjs';
import { hashFile } from '../safety.mjs';
import { evidenceDir, lamp } from './helpers.mjs';

test('independent validator rejects source, unsafe references, format, budget, bounds and unknown fields', async (t) => {
  const base = await evidenceDir('validator');
  const expected = PRODUCT_ASSET_SOURCES.find((p) => p.productId === lamp);
  const publicDir = path.join(REPO_ROOT, 'public/products', lamp);
  const before = await hashFile(path.join(publicDir, 'asset-manifest.json'));
  for (const [name, mutate, pattern] of [
    ['source', (m) => { m.source.sha256 = '0'.repeat(64); }, /Source identity/],
    ['source-bytes', (m) => { m.source.bytes++; }, /Source byte/],
    ['budget', (m) => { m.budget.totalCompressedBytes = 5_000_001; }, /match|equal|budget/i],
    ['bounds', (m) => { m.lods[0].bounds.max[0] += 0.1; m.lods[0].bounds.size[0] += 0.1; }, /measured/],
    ['missing-field', (m) => { delete m.normalization.frontAxis; }, /Missing/],
    ['unknown-field', (m) => { m.unreviewed = 'unsafe'; }, /Unknown/],
    ['unsafe-path', (m) => { m.lods[0].files.push('../private'); }, /union/],
    ['lod-order', (m) => { m.lods.reverse(); }, /three LOD/],
    ['nonfinite', (m) => { m.normalization.bounds.size[0] = null; }, /bounds/],
  ]) await t.test(name, async () => {
    const dir = path.join(base, name); await cp(publicDir, dir, { recursive: true });
    const file = path.join(dir, 'asset-manifest.json'), manifest = JSON.parse(await readFile(file, 'utf8'));
    mutate(manifest); await writeFile(file, JSON.stringify(manifest));
    await assert.rejects(verifyProductAssets(dir, expected), pattern);
  });
  await t.test('URI escape is rejected before any NodeIO resource reads', async () => {
    const dir = path.join(base, 'gltf-escape'); await cp(publicDir, dir, { recursive: true });
    const file = path.join(dir, 'lod0.gltf'), gltf = JSON.parse(await readFile(file, 'utf8'));
    gltf.buffers[0].uri = '../forbidden.bin'; await writeFile(file, JSON.stringify(gltf));
    await assert.rejects(verifyProductAssets(dir, expected), /Unsafe asset path/);
  });
  await t.test('raw source is verified on reuse; nonfinite JSON and triangle measures fail', async () => {
    const raw = path.join(base, 'bad-source.glb'); await writeFile(raw, 'wrong raw source');
    await assert.rejects(verifyProductAssets(publicDir, expected, { sourcePath: raw }), /Raw source bytes/);
    const dir = path.join(base, 'nonfinite-json'); await cp(publicDir, dir, { recursive: true });
    const file = path.join(dir, 'asset-manifest.json');
    const text = await readFile(file, 'utf8'); await writeFile(file, text.replace('"triangles": 16832', '"triangles": 1e400'));
    await assert.rejects(verifyProductAssets(dir, expected), /Nonfinite/);
  });
  await t.test('required extension and KTX compression/mips are independently read', async () => {
    const dir = path.join(base, 'wrong-format'); await cp(publicDir, dir, { recursive: true });
    const file = path.join(dir, 'lod0.gltf'), gltf = JSON.parse(await readFile(file, 'utf8'));
    gltf.extensionsRequired = gltf.extensionsRequired.filter((e) => e !== 'KHR_texture_basisu'); await writeFile(file, JSON.stringify(gltf));
    await assert.rejects(verifyProductAssets(dir, expected), /equal|basisu/i);
    const dir2 = path.join(base, 'wrong-mips'); await cp(publicDir, dir2, { recursive: true });
    const manifest = JSON.parse(await readFile(path.join(dir2, 'asset-manifest.json'), 'utf8'));
    const texture = path.join(dir2, manifest.sharedTextures[0].file), bytes = await readFile(texture);
    bytes.writeUInt32LE(1, 40); await writeFile(texture, bytes);
    await assert.rejects(verifyProductAssets(dir2, expected), /KTX2 header|mip|equal/);
  });
  await t.test('extra directories/files rejected and the public source is preserved', async () => {
    const dir = path.join(base, 'extra'); await cp(publicDir, dir, { recursive: true });
    await mkdir(path.join(dir, 'unexpected')); await assert.rejects(verifyProductAssets(dir, expected), /Unknown output/);
    assert.deepEqual(await hashFile(path.join(publicDir, 'asset-manifest.json')), before);
  });
});

test('coherent half-scale LODs cannot retain original source Product dimensions', async () => {
  const base = await evidenceDir('coherent-scaled-output');
  const publicDir = path.join(REPO_ROOT, 'public/products', lamp);
  const expected = PRODUCT_ASSET_SOURCES.find((p) => p.productId === lamp);
  const original = await verifyProductAssets(publicDir, expected);
  const dir = path.join(base, 'controlled-half-scale');
  await cp(publicDir, dir, { recursive: true, errorOnExist: true, force: false });
  const manifestPath = path.join(dir, 'asset-manifest.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  let lod0;
  // Controlled copied fixture, not native conversion: regenerate every LOD's
  // measurements and bytes coherently while preserving source/dimension claims.
  for (const lod of manifest.lods) {
    const file = path.join(dir, `lod${lod.level}.gltf`);
    const gltf = JSON.parse(await readFile(file, 'utf8'));
    for (const scene of gltf.scenes) {
      const index = gltf.nodes.length;
      gltf.nodes.push({ name: 'Controlled half-scale fixture', scale: [0.5, 0.5, 0.5], children: [...scene.nodes] });
      scene.nodes = [index];
    }
    await writeFile(file, `${JSON.stringify(gltf, null, 1)}\n`);
    const measured = await measureGltf(file);
    lod.bounds = { min: measured.min, max: measured.max, size: measured.size };
    lod.triangles = measured.triangles;
    lod.vertices = measured.vertices;
    lod.exclusiveBytes = 0;
    for (const relative of lod.files) lod.exclusiveBytes += (await stat(path.join(dir, relative))).size;
    if (lod.level === 0) lod0 = measured;
    if (lod.postSimplificationNormalization) lod.postSimplificationNormalization.maxBoundsDeltaFromLod0M = maxBoundsDelta(measured, lod0);
  }
  manifest.budget.totalCompressedBytes = manifest.lods.reduce((sum, lod) => sum + lod.exclusiveBytes, 0) + manifest.budget.sharedBytes;
  assert.deepEqual(manifest.source, original.manifest.source);
  assert.deepEqual(manifest.normalization, original.manifest.normalization);
  assert(lod0.size.every((size, axis) => Math.abs(size * 2 - manifest.normalization.bounds.size[axis]) < 0.0001));
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  let failure;
  try { await verifyProductAssets(dir, expected); } catch (error) { failure = error; }
  await writeFile(path.join(base, 'SCALED-OUTPUT-REJECTION.json'), `${JSON.stringify({
    kind: 'controlled-coherent-scaled-output-negative-test', realNativeConversion: false,
    ownerSample: 'UNRUN', scale: 0.5, declaredProductDimensions: manifest.normalization.bounds.size,
    measuredPublishedLOD0Dimensions: lod0.size, acceptedByValidator: !failure, error: failure?.message ?? null,
  }, null, 2)}\n`, { flag: 'wx' });
  assert(failure, 'Coherent half-scale output must be rejected despite matching per-LOD metadata');
  assert.match(failure.message, /lod0 measured bounds.*canonical normalized source/);
  assert.deepEqual((await verifyProductAssets(publicDir, expected)).files, original.files);
});

test('coherent reduced-topology LOD0 cannot claim the canonical full source geometry', async () => {
  const base = await evidenceDir('coherent-reduced-topology');
  const publicDir = path.join(REPO_ROOT, 'public/products', lamp);
  const expected = PRODUCT_ASSET_SOURCES.find((p) => p.productId === lamp);
  const original = await verifyProductAssets(publicDir, expected);
  const dir = path.join(base, 'controlled-reduced-topology');
  await cp(publicDir, dir, { recursive: true, errorOnExist: true, force: false });
  const file = path.join(dir, 'lod0.gltf');
  const gltf = JSON.parse(await readFile(file, 'utf8'));
  const primitive = gltf.meshes.flatMap((mesh) => mesh.primitives).find((p) => p.indices !== undefined);
  const indices = gltf.accessors[primitive.indices];
  assert(indices.count > 3);
  // A shorter index accessor really removes a triangle from the drawn topology;
  // keep all positions/buffers, canonical bounds and source identity untouched.
  indices.count -= 3;
  await writeFile(file, `${JSON.stringify(gltf, null, 1)}\n`);
  const measured = await measureGltf(file);
  const manifest = JSON.parse(await readFile(path.join(dir, 'asset-manifest.json'), 'utf8'));
  const lod = manifest.lods[0];
  assert.deepEqual({ min: measured.min, max: measured.max, size: measured.size }, lod.bounds);
  assert(measured.triangles < manifest.source.triangles && measured.triangles > manifest.lods[1].triangles);
  lod.triangles = measured.triangles; lod.vertices = measured.vertices;
  lod.exclusiveBytes = 0;
  for (const relative of lod.files) lod.exclusiveBytes += (await stat(path.join(dir, relative))).size;
  manifest.budget.totalCompressedBytes = manifest.lods.reduce((sum, item) => sum + item.exclusiveBytes, 0) + manifest.budget.sharedBytes;
  await writeFile(path.join(dir, 'asset-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  let failure;
  try { await verifyProductAssets(dir, expected); } catch (error) { failure = error; }
  await writeFile(path.join(base, 'REDUCED-TOPOLOGY-REJECTION.json'), `${JSON.stringify({
    kind: 'controlled-coherent-reduced-topology-negative-test', realNativeConversion: false, ownerSample: 'UNRUN',
    canonicalTriangles: manifest.source.triangles, measuredLod0Triangles: measured.triangles,
    boundsUnchanged: true, acceptedByValidator: !failure, error: failure?.message ?? null,
  }, null, 2)}\n`, { flag: 'wx' });
  assert(failure, 'Coherent reduced-topology LOD0 must be rejected');
  assert.match(failure.message, /LOD0.*canonical source triangle count/);
  assert.deepEqual((await verifyProductAssets(publicDir, expected)).files, original.files);
});
