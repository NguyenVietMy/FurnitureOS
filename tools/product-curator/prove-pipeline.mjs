// Exactly one real acceptance, through default server/UI initialization and HTTP.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { createCurator } from './server.mjs';
import { durableFile } from './store.mjs';
import path from 'node:path';

const args = process.argv.slice(2);
assert(args.length === 4 && args[0] === '--state-dir' && args[2] === '--product-id', 'Usage: node tools/product-curator/prove-pipeline.mjs --state-dir <fresh-external-directory> --product-id lamp-rivet-harper-brass');
assert.equal(args[3], 'lamp-rivet-harper-brass', 'Proof is bounded to the approved lamp');
const originalNodeEnv = process.env.NODE_ENV;
const app = await createCurator({ stateDir: args[1], actor: 'automated' });
try {
  assert.equal(process.env.NODE_ENV, originalNodeEnv, 'Default buildUI must restore NODE_ENV');
  assert.equal(app.engine.state.attempts.length, 0, 'Use a fresh proof workspace, never rerun over evidence');
  const get = async (route) => { const response = await fetch(`${app.origin}${route}`); assert.equal(response.status, 200); return response.json(); };
  let state = await get('/api/state');
  const mutate = async (data) => {
    const response = await fetch(`${app.origin}/api/mutate`, { method: 'POST', headers: { Origin: app.origin, 'Content-Type': 'application/json', 'X-Curator-Token': state.token }, body: JSON.stringify({ ...data, revision: state.revision, opId: randomUUID() }) });
    const result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    state = { ...result.state, token: state.token };
  };
  await mutate({ type: 'tags', productId: args[3], styles: ['style-01'], rooms: ['living-room'] });
  await mutate({ type: 'accept', productId: args[3] });
  await app.engine.work;
  if (app.engine.fatal) throw app.engine.fatal;
  const attempt = app.engine.state.attempts[0];
  assert.equal(attempt.status, 'succeeded', JSON.stringify(attempt));
  const entry = await get('/api/catalogue?roomType=living-room&privateStyleId=style-01');
  assert.equal(entry.length, 1);
  assert.deepEqual(entry[0].roomTypes, ['living-room']);
  assert.equal((await get('/api/catalogue?roomType=bedroom')).length, 0);
  const mesh = await fetch(`${app.origin}/mesh/attempt/${attempt.id}/lod0.gltf`);
  assert.equal(mesh.status, 200);
  const report = app.engine.report();
  assert.equal(report.ownerEvidenceStatus, 'UNRUN');
  await durableFile(path.join(app.engine.root, 'REAL-PIPELINE-PROOF.json'), { command: process.argv, origin: app.origin, nodeEnvRestored: process.env.NODE_ENV === originalNodeEnv, actor: 'automated', ownerSample: 'UNRUN', stateRevision: app.engine.state.revision, attempt, catalogue: entry, report });
  console.log(JSON.stringify({ verdict: 'PASS', kind: 'real-native-conversion-through-default-server', productId: args[3], attemptId: attempt.id, durationMs: attempt.durationMs, files: attempt.files, proof: path.join(app.engine.root, 'REAL-PIPELINE-PROOF.json'), ownerSample: 'UNRUN' }, null, 2));
} finally { await app.close(); }
