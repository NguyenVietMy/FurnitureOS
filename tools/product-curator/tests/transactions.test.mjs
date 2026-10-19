import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, writeFile, readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { buildProduct } from '../../../scripts/build-product-assets.mjs';
import { Engine } from '../engine.mjs';
import { digest, hashFile, ownRoot, nativeTool, NATIVE } from '../safety.mjs';
import { evidenceDir, controlledOutput, controlledRunner, lamp, operation, waitSettled } from './helpers.mjs';

test('reusable builder import does not run CLI; bad cached source is preserved before work/output/native execution', async () => {
  const dir = await evidenceDir('builder-source-reuse');
  const sourceDir = path.join(dir, 'source'); await mkdir(sourceDir);
  const sourceFile = path.join(sourceDir, 'controlled.glb'); await writeFile(sourceFile, 'controlled invalid source');
  const before = await hashFile(sourceFile);
  const product = { productId: 'controlled', sourceFrontAxis: '+z', sourceUrl: 'https://never-request.invalid/source', sourceFile: 'controlled.glb', sourceSha256: '0'.repeat(64), sourceBytes: before.bytes };
  const options = { sourceDir, workDir: path.join(dir, 'work'), outputDir: path.join(dir, 'output'), bin: path.join(dir, 'never-executed.exe') };
  await assert.rejects(buildProduct(product, options), /Checksum mismatch/);
  assert.deepEqual(await hashFile(sourceFile), before);
  await assert.rejects(stat(options.workDir), { code: 'ENOENT' });
  await assert.rejects(stat(options.outputDir), { code: 'ENOENT' });
  await assert.rejects(buildProduct({ ...product, sourceSha256: before.sha256, sourceBytes: before.bytes + 1 }, options), /Byte-size mismatch/);
  assert.deepEqual(await hashFile(sourceFile), before);
});

test('native cached override cannot escape owned tools directory', async () => {
  const root = await ownRoot(await evidenceDir('native-path'));
  await mkdir(path.join(root, 'tools'));
  await writeFile(path.join(root, 'tools/verified-tool.json'), JSON.stringify({ archive: { sha256: NATIVE.sha256, bytes: 1, file: '../outside.zip' }, binary: { file: '../outside.exe', sha256: '0'.repeat(64), bytes: 1 } }));
  await assert.rejects(nativeTool(root), /escaped|Windows only/);
});

test('dead writer lock is preserved; ACTIVE backwards time becomes INVALID in controlled owner state', async (t) => {
  const stateDir = await evidenceDir('stale-writer-CONTROLLED');
  let now = 5000;
  let engine = await Engine.open({ stateDir, actor: 'owner', controlled: true, clock: () => now });
  t.after(async () => { if (engine) await engine.close(); });
  await engine.close(); engine = null;
  const lockPath = path.join(stateDir, 'writer.lock');
  const child = spawnSync(process.execPath, ['-e', 'require("node:fs").writeFileSync(process.argv[1],JSON.stringify({pid:process.pid,id:"controlled-dead-writer"}))', lockPath], { windowsHide: true });
  assert.equal(child.status, 0);
  const before = await hashFile(lockPath);
  engine = await Engine.open({ stateDir, actor: 'owner', controlled: true, clock: () => now });
  const preserved = (await readdir(stateDir)).find((f) => f.startsWith('stale-lock-'));
  assert(preserved); assert.deepEqual(await hashFile(path.join(stateDir, preserved)), before);
  await operation(engine, { type: 'start' }); now += 1000;
  await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
  now -= 2000;
  await assert.rejects(operation(engine, { type: 'reject', productId: lamp }), /backwards/);
  assert.equal(engine.state.sample.status, 'INVALID');
  assert.equal(engine.state.candidates.find((c) => c.productId === lamp).decision, null);
  assert.equal(engine.report().ownerEvidenceStatus, 'UNRUN');
});

test('commit filesystem fault cannot acknowledge a new selection or destroy prior successful output', async (t) => {
  const stateDir = await evidenceDir('acceptance-commit-fault');
  const engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner() });
  t.after(() => engine.close());
  await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['living-room'] });
  await operation(engine, { type: 'accept', productId: lamp }); await waitSettled(engine);
  const old = engine.state.attempts[0];
  const oldFile = path.join(stateDir, 'attempts', old.id, 'output/lod0.gltf'), oldHash = await hashFile(oldFile);
  await operation(engine, { type: 'undo' });
  engine.runner = async (input) => {
    const result = await controlledOutput(input);
    const target = path.join(stateDir, 'journal', `${String(engine.state.revision + 1).padStart(10, '0')}.json`);
    await mkdir(target); return result;
  };
  await operation(engine, { type: 'accept', productId: lamp });
  await engine.work; await engine.queue;
  assert(engine.fatal); assert(engine.store.poisoned);
  assert.equal(engine.state.candidates.find((c) => c.productId === lamp).selection, null);
  assert.equal(engine.state.attempts.filter((a) => a.status === 'succeeded').length, 1);
  assert.deepEqual(await hashFile(oldFile), oldHash);
  assert((await readdir(path.join(stateDir, 'journal'))).some((f) => f.endsWith('.pending')));
  await assert.rejects(operation(engine, { type: 'reject', productId: lamp }), /in flight|write failed/);
});
