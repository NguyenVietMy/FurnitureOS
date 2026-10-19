import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile, readdir, symlink, stat, rename } from 'node:fs/promises';
import path from 'node:path';
import { Engine } from '../engine.mjs';
import { ownRoot, assertLocalContext, hashFile, ownedPath } from '../safety.mjs';
import { REPO_ROOT } from '../../../scripts/lib/paths.mjs';
import { evidenceDir, controlledRunner, operation, waitSettled, lamp } from './helpers.mjs';

test('bounded durable review, conflicts, replay, Catalogue filters, retained attempts and undo', async (t) => {
  const stateDir = await evidenceDir('contracts');
  let engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner({ failFirst: true }) });
  t.after(async () => { if (engine) await engine.close(); });
  const sourceBefore = await hashFile(path.join(REPO_ROOT, 'public/products', lamp, 'asset-manifest.json'));
  await t.test('exact 20 frozen identities, fresh tags, missing tags and wrong identity rejected', async () => {
    assert.equal(engine.state.candidates.length, 20);
    assert(engine.state.candidates.every((c) => !c.styles.length && !c.rooms.length));
    assert.equal(engine.state.freeze.orderedSources.length, 20);
    await assert.rejects(operation(engine, { type: 'accept', productId: lamp }), /at least one/);
    await assert.rejects(operation(engine, { type: 'reject', productId: 'invented-product' }), /frozen 20/);
    await assert.rejects(operation(engine, { type: 'navigate', cursor: 20 }), /0–19/);
    await assert.rejects(operation(engine, { type: 'tags', productId: lamp, styles: ['unknown'], rooms: ['bedroom'] }), /known/);
  });
  await t.test('single writer, durable tag provenance, stale updates and exact duplicate replay', async () => {
    await assert.rejects(Engine.open({ stateDir, actor: 'automated' }), /live writer/);
    const op = { type: 'tags', productId: lamp, styles: ['style-02'], rooms: ['living-room'], opId: randomUUID(), revision: engine.state.revision };
    await engine.mutate(op);
    const revision = engine.state.revision;
    assert.equal((await engine.mutate(op)).replayed, true);
    assert.equal(engine.state.revision, revision);
    await assert.rejects(engine.mutate({ ...op, rooms: ['bedroom'] }), /reused/);
    await assert.rejects(operation(engine, { type: 'navigate', cursor: 1 }, { revision: 0 }), /another tab/);
    assert(engine.store.events.some((e) => e.type === 'tags' && e.tags.styles[0] === 'style-02'));
  });
  await t.test('cursor and unsaved tags survive clean server restart; no auto acceptance', async () => {
    await operation(engine, { type: 'navigate', cursor: 19 });
    await engine.close(); engine = null;
    engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner({ failFirst: true }) });
    assert.equal(engine.state.cursor, 19);
    assert.deepEqual(engine.state.candidates.find((c) => c.productId === lamp).styles, ['style-02']);
    assert.equal(engine.state.candidates.find((c) => c.productId === lamp).decision, null);
  });
  await t.test('failure stage and retry preserve inputs, failed bytes and exactly one logical Product', async () => {
    const accept = { type: 'accept', productId: lamp, opId: randomUUID(), revision: engine.state.revision };
    await engine.mutate(accept);
    assert.equal(engine.busy, true);
    await engine.mutate(accept);
    await assert.rejects(operation(engine, { type: 'undo' }), /in flight/);
    await assert.rejects(operation(engine, { type: 'retry', productId: lamp }), /in flight/);
    await waitSettled(engine);
    assert.equal(engine.state.attempts.length, 1);
    assert.equal(engine.state.attempts[0].status, 'failed');
    const failed = path.join(stateDir, 'attempts', engine.state.attempts[0].id, 'retained-failure.txt');
    const before = await hashFile(failed);
    await operation(engine, { type: 'retry', productId: lamp });
    await waitSettled(engine);
    assert.equal(engine.state.attempts[1].status, 'succeeded');
    assert.deepEqual(await hashFile(failed), before);
    const entries = await engine.entries({ roomType: 'living-room', privateStyleId: 'style-02' });
    assert.equal(entries.length, 1); assert.equal(entries[0].id, lamp);
    assert.deepEqual(entries[0].roomTypes, ['living-room']);
    assert.equal((await engine.entries({ roomType: 'bedroom' })).length, 0);
    assert.equal((await engine.entries({ privateStyleId: 'style-01' })).length, 0);
    await assert.rejects(operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] }), /Undo/);
    assert.equal(engine.report().ownerEvidenceStatus, 'UNRUN');
    assert.equal(engine.report().counts.retries, 1);
  });
  await t.test('undo keeps accepted files; subsequent failed acceptance leaves prior bytes immutable', async () => {
    const attempt = engine.state.attempts[1];
    const acceptedFile = path.join(stateDir, 'attempts', attempt.id, 'output/lod0.gltf');
    const before = await hashFile(acceptedFile);
    await operation(engine, { type: 'undo' });
    assert.equal((await engine.entries()).length, 0);
    assert.equal(engine.state.candidates[engine.state.cursor].productId, lamp);
    assert.deepEqual(await hashFile(acceptedFile), before);
    engine.runner = controlledRunner({ failFirst: true });
    await operation(engine, { type: 'accept', productId: lamp });
    await waitSettled(engine);
    assert.equal(engine.state.attempts[2].status, 'failed');
    assert.deepEqual(await hashFile(acceptedFile), before);
    await operation(engine, { type: 'reject', productId: lamp });
    await operation(engine, { type: 'undo' });
    assert.equal(engine.state.candidates.find((c) => c.productId === lamp).decision, null);
    assert.deepEqual(await hashFile(path.join(REPO_ROOT, 'public/products', lamp, 'asset-manifest.json')), sourceBefore);
  });
  await t.test('committed output corruption fails closed on restart, without deleting corrupt bytes', async () => {
    const file = path.join(stateDir, 'attempts', engine.state.attempts[1].id, 'output/lod0.gltf');
    await engine.close(); engine = null;
    await writeFile(file, 'corrupt committed artifact\n');
    await assert.rejects(Engine.open({ stateDir, actor: 'automated' }), /JSON|Unexpected|token/);
    assert.equal(await readFile(file, 'utf8'), 'corrupt committed artifact\n');
  });
});

test('foreign checkouts, linked paths, dangerous roots and hosted contexts are rejected before writes', async () => {
  const base = await evidenceDir('path-boundaries');
  const foreign = path.join(base, 'unrelated-checkout');
  await mkdir(foreign);
  await writeFile(path.join(foreign, '.git'), 'gitdir: unrelated metadata\n');
  for (const directory of ['fresh-state', 'public/new-state', 'dist/new-state']) {
    const target = path.join(foreign, directory);
    await assert.rejects(ownRoot(target), /Git checkout/);
    await assert.rejects(stat(target), { code: 'ENOENT' });
  }
  assert.deepEqual(await readdir(foreign), ['.git']);
  await assert.rejects(ownRoot(path.join(REPO_ROOT, 'public', 'forbidden-curator-state')), /Git checkout/);
  await assert.rejects(ownRoot(path.parse(base).root), /Dangerous|too broad|overlaps/);
  const populated = path.join(base, 'foreign-populated'); await mkdir(populated); await writeFile(path.join(populated, 'keep.txt'), 'retain');
  await assert.rejects(ownRoot(populated), /ENOENT|Unknown/);
  assert.equal(await readFile(path.join(populated, 'keep.txt'), 'utf8'), 'retain');
  const owned = await ownRoot(path.join(base, 'owned'));
  await assert.rejects(ownedPath(owned, '..', 'escape'), /escaped/);
  const linked = path.join(base, 'linked');
  await symlink(foreign, linked, process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(ownRoot(path.join(linked, 'state')), /Symlink|reparse/);
  for (const env of [{ CI: 'true' }, { VERCEL: '1' }, { NODE_ENV: 'production' }, { GLTFPACK_PATH: 'unsafe' }, { FURNITUREOS_ASSET_WORK_DIR: 'unsafe' }]) assert.throws(() => assertLocalContext(env), /refuses|Unset/);
});

test('truncated final write, changed identity and commit filesystem fault preserve bytes and fail closed', async (t) => {
  const stateDir = await evidenceDir('journal-fault');
  let engine = await Engine.open({ stateDir, actor: 'automated' });
  t.after(async () => { if (engine) await engine.close(); });
  const journal = path.join(stateDir, 'journal');
  // Make the next immutable record target a directory: atomic rename must fail,
  // no acknowledgement or successful event may be fabricated.
  const blocked = path.join(journal, '0000000001.json'); await mkdir(blocked);
  await assert.rejects(operation(engine, { type: 'navigate', cursor: 7 }));
  assert.equal(engine.state.cursor, 0); assert.equal(engine.store.poisoned, true);
  assert((await readdir(journal)).some((f) => f.endsWith('.pending')));
  await engine.close(); engine = null;
  await assert.rejects(Engine.open({ stateDir, actor: 'automated' }), /Incomplete|unknown/);
  assert((await readdir(journal)).some((f) => f.endsWith('.pending')));
  const dir2 = await evidenceDir('identity-corruption');
  engine = await Engine.open({ stateDir: dir2, actor: 'automated' });
  await engine.close(); engine = null;
  const file = path.join(dir2, 'journal/0000000000.json');
  const data = JSON.parse(await readFile(file, 'utf8')); data.state.freeze.seedSha256 = '0'.repeat(64);
  // Even a self-consistent modified snapshot must reject current seed binding.
  const { hash: ignored, ...payload } = data;
  const { digest } = await import('../safety.mjs'); data.hash = digest(JSON.stringify(payload));
  await writeFile(file, JSON.stringify(data));
  const before = await hashFile(file);
  await assert.rejects(Engine.open({ stateDir: dir2, actor: 'automated' }), /seed identity/);
  assert.deepEqual(await hashFile(file), before);
});

test('abandoned acceptance is interrupted on restart, never inferred from staged output', async (t) => {
  const stateDir = await evidenceDir('interrupted');
  let engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner() });
  t.after(async () => { if (engine) await engine.close(); });
  await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
  // Controlled crash boundary: commit the start transaction but suppress worker
  // launch, then release ownership exactly as a dead writer would leave it.
  engine.launch = () => {};
  await operation(engine, { type: 'accept', productId: lamp });
  await engine.close(); engine = null;
  engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner() });
  assert.equal(engine.state.attempts[0].status, 'interrupted');
  assert.equal(engine.state.candidates.find((c) => c.productId === lamp).decision, null);
  assert.equal((await engine.entries()).length, 0);
  await operation(engine, { type: 'retry', productId: lamp }); await waitSettled(engine);
  assert.equal((await engine.entries()).length, 1);
});

test('a missing or empty initialized journal cannot silently reset durable review state', async () => {
  const stateDir = await evidenceDir('missing-journal');
  const engine = await Engine.open({ stateDir, actor: 'automated' });
  await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
  await engine.close();
  const journal = await ownedPath(stateDir, 'journal');
  const retained = await ownedPath(stateDir, 'retained-original-journal');
  const original = await hashFile(path.join(journal, '0000000001.json'));
  await rename(journal, retained);
  await assert.rejects(Engine.open({ stateDir, actor: 'automated' }), /Initialized journal is missing/);
  await assert.rejects(stat(journal), { code: 'ENOENT' });
  assert.deepEqual(await hashFile(path.join(retained, '0000000001.json')), original);
  await mkdir(journal);
  await assert.rejects(Engine.open({ stateDir, actor: 'automated' }), /Initialized journal is empty/);
  assert.deepEqual(await readdir(journal), []);
  assert.deepEqual(await hashFile(path.join(retained, '0000000001.json')), original);
});

test('tag-only undo preserves failed and restart-interrupted acceptance retry lifecycle', async (t) => {
  for (const outcome of ['failed', 'interrupted']) await t.test(outcome, async () => {
    const stateDir = await evidenceDir(`tag-undo-${outcome}`);
    let engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner({ failFirst: true }) });
    try {
      // Undo the second tag event after failure: the first explicit choices
      // remain sufficient for retry, independent of the retained attempt error.
      await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
      await operation(engine, { type: 'tags', productId: lamp, styles: ['style-02'], rooms: ['living-room'] });
      if (outcome === 'interrupted') engine.launch = () => {};
      await operation(engine, { type: 'accept', productId: lamp });
      if (outcome === 'failed') await waitSettled(engine);
      else {
        await engine.close(); engine = null;
        engine = await Engine.open({ stateDir, actor: 'automated', runner: controlledRunner() });
      }
      const attempt = engine.state.attempts[0], candidate = engine.state.candidates.find((c) => c.productId === lamp);
      assert.equal(attempt.status, outcome);
      const error = candidate.error;
      const retained = path.join(stateDir, 'attempts', attempt.id, outcome === 'failed' ? 'retained-failure.txt' : 'input.json');
      const before = await hashFile(retained);
      await operation(engine, { type: 'undo' });
      const undone = engine.state.candidates.find((c) => c.productId === lamp);
      assert.deepEqual(undone.styles, ['style-01']); assert.deepEqual(undone.rooms, ['bedroom']);
      assert.equal(undone.error, error);
      assert.equal(engine.view().candidates.find((c) => c.productId === lamp).error, error);
      assert.equal(engine.state.attempts[0].status, outcome);
      await operation(engine, { type: 'retry', productId: lamp }); await waitSettled(engine);
      assert.equal(engine.report().counts.retries, 1);
      assert.equal(engine.report().counts.failures, 1);
      assert.equal(engine.state.attempts.length, 2);
      assert.equal(engine.state.attempts[1].status, 'succeeded');
      assert.equal((await engine.entries()).length, 1);
      assert.deepEqual(await hashFile(retained), before);
    } finally { if (engine) await engine.close(); }
  });
});
