import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import http from 'node:http';
import { createCurator } from '../server.mjs';
import { evidenceDir, controlledRunner, lamp, waitSettled } from './helpers.mjs';

async function client(app) {
  let state;
  const read = async () => { const r = await fetch(`${app.origin}/api/state`); assert.equal(r.status, 200); state = await r.json(); return state; };
  await read();
  return { read, post: async (data, expected = 200) => {
    await read();
    const r = await fetch(`${app.origin}/api/mutate`, { method: 'POST', headers: { Origin: app.origin, 'Content-Type': 'application/json', 'X-Curator-Token': state.token }, body: JSON.stringify({ ...data, revision: state.revision, opId: randomUUID() }) });
    const result = await r.json(); assert.equal(r.status, expected, JSON.stringify(result)); return result;
  } };
}
test('HTTP local boundary and controlled owner pre-start/pause/finish protocol', async (t) => {
  const stateDir = await evidenceDir('http-owner-CONTROLLED');
  let now = 10000;
  let app = await createCurator({ stateDir, actor: 'owner', controlled: true, clock: () => now, runner: controlledRunner({ delay: 150 }) });
  t.after(async () => { if (app) await app.close(); });
  const c = await client(app);
  const request = async (route, expected) => { const r = await fetch(`${app.origin}${route}`); assert.equal(r.status, expected, route); return r; };
  const preview = app.engine.state.freeze.previews[lamp];
  const meshRoute = `/mesh/original/${preview.identity}/${lamp}/lod0.gltf`;
  await t.test('pre-start candidate details, Mesh, Catalogue and decoders unavailable', async () => {
    const state = await c.read(); assert.equal(state.candidates, undefined); assert.equal(state.styles, undefined);
    await request(meshRoute, 423); await request('/api/catalogue', 423); await request('/decoders/basis/basis_transcoder.js', 423);
    const report = await (await request('/api/report', 200)).json(); assert.equal(report.ownerEvidenceStatus, 'UNRUN'); assert.equal(report.candidates, undefined);
    await c.post({ type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] }, 423);
    await c.post({ type: 'navigate', cursor: 2 }, 423);
    for (const route of ['/@fs/api/catalogue/providers/abo-seed.json', '/api/catalogue/providers/abo-seed.json', '/public/products/lod0.gltf', `/products/${lamp}/lod0.gltf`, '/ui/main.tsx']) await request(route, 404);
  });
  await t.test('Host, Origin, CSRF token, media type, body size and unsupported methods', async () => {
    const r = await fetch(`${app.origin}/api/state`, { headers: { Origin: 'https://evil.example' } }); assert.equal(r.status, 403);
    const hostStatus = await new Promise((resolve, reject) => {
      const req = http.get(`${app.origin}/api/state`, { headers: { Host: `evil.example:${new URL(app.origin).port}` } }, (response) => { response.resume(); resolve(response.statusCode); }); req.on('error', reject);
    }); assert.equal(hostStatus, 403);
    const state = await c.read();
    for (const headers of [{ Origin: app.origin, 'Content-Type': 'application/json' }, { Origin: app.origin, 'Content-Type': 'text/plain', 'X-Curator-Token': state.token }, { 'Content-Type': 'application/json', 'X-Curator-Token': state.token }]) {
      assert.equal((await fetch(`${app.origin}/api/mutate`, { method: 'POST', headers, body: '{}' })).status, 403);
    }
    const oversized = await fetch(`${app.origin}/api/mutate`, { method: 'POST', headers: { Origin: app.origin, 'Content-Type': 'application/json', 'X-Curator-Token': state.token }, body: JSON.stringify({ pad: 'x'.repeat(17000) }) }); assert.equal(oversized.status, 413);
    assert.equal((await fetch(`${app.origin}/api/state`, { method: 'OPTIONS' })).status, 405);
    assert.equal((await fetch(`${app.origin}/api/state`)).headers.get('access-control-allow-origin'), null);
  });
  await t.test('pause immediately after accept denied; conversion/commit time included', async () => {
    await c.post({ type: 'start' }); now += 2000;
    await request(meshRoute, 200);
    await c.post({ type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['living-room'] });
    await c.post({ type: 'accept', productId: lamp });
    now += 5000;
    await c.post({ type: 'pause' }, 409);
    assert.equal(app.engine.state.sample.status, 'ACTIVE');
    await waitSettled(app.engine);
    now += 1000;
    await c.post({ type: 'pause' });
    assert.equal(app.engine.state.sample.activeMs, 8000);
    assert.equal(app.engine.state.attempts[0].durationMs, 5000);
    const state = await c.read(); assert.equal(state.candidates, undefined);
    await request(meshRoute, 423);
    await request(`/mesh/attempt/${app.engine.state.attempts[0].id}/lod0.gltf`, 423);
    await request('/decoders/basis/basis_transcoder.wasm', 423);
    for (const type of ['accept', 'reject', 'retry', 'undo', 'navigate', 'tags']) await c.post({ type, productId: lamp, styles: ['style-02'], rooms: ['bedroom'], cursor: 2 }, 423);
  });
  await t.test('durably paused restart resumes without subtracting active waits; invalid finish rejected', async () => {
    await app.close(); app = null; now += 100000;
    app = await createCurator({ stateDir, actor: 'owner', controlled: true, clock: () => now, runner: controlledRunner() });
    const c2 = await client(app);
    assert.equal((await c2.read()).sample.status, 'PAUSED');
    await c2.post({ type: 'resume' }); now += 3000;
    await c2.post({ type: 'finish' }, 422);
    assert.equal(app.engine.elapsed(), 11000);
    const report = app.engine.report(); assert.equal(report.timing.validOwnerTiming, false); assert.equal(report.estimate, null);
    await app.close(); app = null; now += 1000;
    app = await createCurator({ stateDir, actor: 'owner', controlled: true, clock: () => now });
    assert.equal(app.engine.state.sample.status, 'INVALID');
    const c3 = await client(app); await c3.post({ type: 'reject', productId: lamp }, 423);
    assert.match(app.engine.report().timing.invalidReason, /downtime/);
  });
});

test('controlled owner completion exports all 20 decisions, rejects/undo history and undefined zero-yield rate', async (t) => {
  const app = await createCurator({ stateDir: await evidenceDir('http-finished-CONTROLLED'), actor: 'owner', controlled: true });
  t.after(() => app.close());
  const c = await client(app);
  await c.post({ type: 'estimate', remainingCandidates: 120 });
  await c.post({ type: 'start' });
  await c.post({ type: 'reject', productId: lamp }); await c.post({ type: 'undo' });
  for (const candidate of app.engine.state.candidates) await c.post({ type: 'reject', productId: candidate.productId });
  await c.post({ type: 'finish' });
  const report = await (await fetch(`${app.origin}/api/report`)).json();
  assert.equal(report.sampleStatus, 'FINISHED'); assert.equal(report.counts.rejected, 20);
  assert.equal(report.counts.undo, 1); assert.equal(report.yield, 0);
  assert.equal(report.timing.secondsPerAccepted, null); assert.equal(report.timing.validOwnerTiming, false);
  assert.equal(report.ownerEvidenceStatus, 'UNRUN'); assert.equal(report.evidenceKind, 'controlled-automated-owner-state');
  assert.equal(report.estimate, null); assert.equal(report.history.filter((e) => e.type === 'reject').length, 21);
  await c.post({ type: 'undo' }, 423);
});

test('status and busy Pause respond while acceptance commit is blocked on durable I/O', async (t) => {
  const app = await createCurator({ stateDir: await evidenceDir('http-commit-window-CONTROLLED'), actor: 'owner', controlled: true, runner: controlledRunner() });
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let atCommit = false;
  const commit = app.engine.store.commit.bind(app.engine.store);
  app.engine.store.commit = async (state, event) => {
    if (event.type === 'accepted') { atCommit = true; await gate; }
    return commit(state, event);
  };
  t.after(async () => { release(); await app.close(); });
  const c = await client(app);
  await c.post({ type: 'start' });
  await c.post({ type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
  await c.post({ type: 'accept', productId: lamp });
  while (!atCommit) { await new Promise((resolve) => setTimeout(resolve, 20)); }
  const status = await fetch(`${app.origin}/api/state`, { signal: AbortSignal.timeout(2000) });
  assert.equal(status.status, 200); assert.equal((await status.json()).busy, true);
  const current = await c.read();
  const pause = await fetch(`${app.origin}/api/mutate`, { method: 'POST', signal: AbortSignal.timeout(2000), headers: { Origin: app.origin, 'Content-Type': 'application/json', 'X-Curator-Token': current.token }, body: JSON.stringify({ type: 'pause', opId: randomUUID(), revision: current.revision }) });
  assert.equal(pause.status, 409); assert.match((await pause.json()).error, /Cannot pause/);
  assert.equal(app.engine.state.sample.status, 'ACTIVE');
  release(); await waitSettled(app.engine); await c.post({ type: 'pause' });
  assert.equal(app.engine.state.sample.status, 'PAUSED');
});
