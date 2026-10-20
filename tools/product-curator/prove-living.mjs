// Bounded native HTTP proof. Every decision here is explicitly controlled;
// it never opens the real owner's workspace or produces promotable metadata.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { readFile, appendFile } from 'node:fs/promises';
import { createCurator } from './server.mjs';
import { durableFile } from './store.mjs';
import { promotionInventory, applyControlledFixture } from './promote-living.mjs';
import { LIVING_PROFILE } from './profiles.mjs';
import { hashFile } from './safety.mjs';

const args = process.argv.slice(2);
assert(args.length === 4 && args[0] === '--state-dir' && args[2] === '--prepared-dir');
const app = await createCurator({ stateDir: args[1], preparedDir: args[3], profile: LIVING_PROFILE, actor: 'owner', controlled: true, ownerIdentity: 'CONTROLLED-AUTOMATED-NOT-OWNER' });
try {
  assert.equal(app.engine.state.attempts.length, 0, 'Use a fresh proof workspace');
  const get = async (route) => { const r = await fetch(`${app.origin}${route}`); assert.equal(r.status, 200); return r.json(); };
  let state = await get('/api/state');
  const mutate = async (data) => {
    state = await get('/api/state');
    const r = await fetch(`${app.origin}/api/mutate`, { method: 'POST', headers: { Origin: app.origin, 'Content-Type': 'application/json', 'X-Curator-Token': state.token }, body: JSON.stringify({ ...data, revision: state.revision, opId: randomUUID() }) });
    const result = await r.json();
    assert.equal(r.status, 200, JSON.stringify(result));
    return result;
  };
  await assert.rejects(promotionInventory(app.engine), /Controlled|pending/);
  await mutate({ type: 'start' });
  for (const p of app.engine.state.freeze.seed.products) {
    await mutate({ type: 'note', productId: p.productId, note: 'CONTROLLED AUTOMATED PIPELINE CHECK ONLY. No owner suitability, upholstery or Style judgment.' });
    await mutate({ type: 'tags', productId: p.productId, styles: ['style-01'], rooms: ['living-room'] });
    await mutate({ type: 'accept', productId: p.productId });
    await app.engine.work;
    await app.engine.queue;
    if (app.engine.fatal) throw app.engine.fatal;
    const a = app.engine.state.attempts.at(-1);
    assert.equal(a.status, 'succeeded', JSON.stringify(a));
    await appendFile(path.join(app.engine.root, 'progress.log'), `${p.productId} ${a.id} validated ${a.files.length} files\n`);
  }
  await mutate({ type: 'finish' });
  assert.equal(app.engine.report().ownerEvidenceStatus, 'UNRUN');
  await assert.rejects(promotionInventory(app.engine), /Controlled/);
  // Mutate only an explicitly controlled in-memory snapshot to test the gate.
  // Restore it before any journal write; no fake owner report is ever created.
  const completed = structuredClone(app.engine.store.state);
  const gateChecks = [];
  for (const [name, change, expected] of [
    ['undone', (s) => { s.candidates[0].selection = null; }, /current acceptance/],
    ['pending', (s) => { s.sample.status = 'ACTIVE'; }, /pending/],
    ['rejected-anchors', (s) => { s.candidates.filter((c) => c.productId.startsWith('sofa-')).forEach((c) => { c.decision = 'rejected'; c.selection = null; }); }, /five functional/],
    ['unsupported-style', (s) => { s.candidates[0].styles = ['style-99']; }, /Style/],
  ]) {
    app.engine.store.state = structuredClone(completed);
    change(app.engine.store.state);
    await assert.rejects(promotionInventory(app.engine, { controlledFixture: true }), expected);
    gateChecks.push(name);
  }
  app.engine.store.state = completed;
  const applied = await applyControlledFixture(app.engine, path.join(app.engine.root, 'CONTROLLED-apply-destination'));
  assert.equal(applied.inventory.version, 'CONTROLLED-NOT-OWNER-NOT-PRODUCTION');
  await assert.rejects(applyControlledFixture(app.engine, applied.root), /Existing|EEXIST/);
  const entry = (await get('/api/catalogue?roomType=living-room&privateStyleId=style-01'));
  assert.equal(entry.length, 8);
  assert.equal((await get('/api/catalogue?roomType=bedroom')).length, 0);
  const proof = { kind: 'CONTROLLED-NATIVE-HTTP-NOT-OWNER', ownerEvidenceStatus: 'UNRUN', command: process.argv, report: app.engine.report(), gateChecks, applied, catalogue: entry };
  await durableFile(path.join(app.engine.root, 'CONTROLLED-LIVING-PROOF.json'), proof);
  console.log(JSON.stringify({ status: 'PASS', ownerGate: 'PENDING', proof: await hashFile(path.join(app.engine.root, 'CONTROLLED-LIVING-PROOF.json')) }));
} finally { await app.close(); }
