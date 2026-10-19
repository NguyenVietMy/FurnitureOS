import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { REPO_ROOT } from '../../../scripts/lib/paths.mjs';
import { verifyProductAssets } from '../../../scripts/lib/verify-product-assets.mjs';
import { project } from '../catalogue.mjs';

export async function evidenceDir(name) {
  const base = process.env.CURATOR_EVIDENCE_DIR ?? path.join(tmpdir(), 'furnitureos-curator-evidence');
  await mkdir(base, { recursive: true });
  return mkdtemp(path.join(base, `${name}-`));
}
export async function controlledOutput({ dir, candidate, attempt, freeze }) {
  const output = path.join(dir, 'output');
  await cp(path.join(REPO_ROOT, 'public/products', candidate.productId), output, { recursive: true, errorOnExist: true, force: false });
  // Distinct valid fixture bytes ensure attempt switching cannot accidentally
  // pass while serving a stable product URL or an old cached scene.
  const gltfFile = path.join(output, 'lod0.gltf');
  const before = (await readFile(gltfFile)).length;
  const gltf = JSON.parse(await readFile(gltfFile, 'utf8'));
  gltf.extras = { controlledAttempt: attempt.id };
  const after = Buffer.from(`${JSON.stringify(gltf)}\n`);
  await writeFile(gltfFile, after);
  const manifestFile = path.join(output, 'asset-manifest.json');
  const manifest = JSON.parse(await readFile(manifestFile, 'utf8'));
  manifest.lods[0].exclusiveBytes += after.length - before;
  manifest.budget.totalCompressedBytes += after.length - before;
  await writeFile(manifestFile, `${JSON.stringify(manifest, null, 2)}\n`);
  const source = freeze.orderedSources.find((s) => s.productId === candidate.productId);
  const validated = await verifyProductAssets(output, source);
  return { kind: 'controlled-published-byte-fixture-NOT-native-conversion', files: validated.files, entry: await project(freeze, candidate, attempt, validated.manifest) };
}
export function controlledBarrier() {
  let enter, release;
  const entered = new Promise((resolve) => { enter = resolve; });
  const released = new Promise((resolve) => { release = resolve; });
  return { entered, release, wait: async () => { enter(); await released; } };
}
export function controlledRunner({ failFirst = false, delay = 40, barrier } = {}) {
  let calls = 0;
  return async (input) => {
    calls++;
    await input.progress('controlled-conversion');
    if (barrier) await barrier.wait();
    else await new Promise((resolve) => setTimeout(resolve, delay));
    if (failFirst && calls === 1) {
      await writeFile(path.join(input.dir, 'retained-failure.txt'), 'Controlled conversion failure. No native conversion was attempted.\n');
      const error = new Error('Controlled conversion failure'); error.stage = 'controlled-conversion'; throw error;
    }
    await input.progress('controlled-validation');
    return controlledOutput(input);
  };
}
export async function waitSettled(engine) {
  await engine.work;
  await engine.queue;
  if (engine.fatal) throw engine.fatal;
}
export async function operation(engine, data, overrides = {}) {
  const { randomUUID } = await import('node:crypto');
  return engine.mutate({ ...data, opId: randomUUID(), revision: engine.state.revision, ...overrides });
}
export const lamp = 'lamp-rivet-harper-brass';
