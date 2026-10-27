import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { installVariantObservation } from './variant-measurement-observer.mjs';
import { createTimingEvidence } from './variant-timing-evidence.mjs';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function page(fetch) {
  const sandbox = vm.createContext({ fetch, URL, Response, TextDecoder, TextEncoder, performance,
    location: { href: 'http://127.0.0.1:3142/design/live' }, addEventListener() {} });
  vm.runInContext(`(${installVariantObservation.toString()})()`, sandbox);
  return sandbox;
}
const flush = async (until) => {
  for (let i = 0; i < 100 && !until(); i++) await new Promise(resolve => setTimeout(resolve, 2));
  assert.ok(until());
};
test('actual UI branch consumes a stream while the clone records terminal usage, including unknowns', async () => {
  let stream, calls = 0;
  const sandbox = page(async () => { calls++; return new Response(new ReadableStream({ start(c) { stream = c; } })); });
  const ui = await sandbox.fetch('/api/live-design/variants', { method: 'POST' });
  const consumed = ui.text();
  const put = value => stream.enqueue(new TextEncoder().encode(JSON.stringify(value) + '\n'));
  put({ type: 'shell' }); put({ type: 'variant', variant: 'A' });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(sandbox.__variantWire.done, false);
  const complete = { type: 'complete', available: ['A'], usage: { known: false, cacheReadInputTokens: null } };
  put(complete); stream.close();
  assert.match(await consumed, /cacheReadInputTokens/);
  await flush(() => sandbox.__variantWire.done);
  assert.equal(JSON.stringify(sandbox.__variantWire.outcome), JSON.stringify(complete));
  assert.equal(sandbox.__variantWire.error, null); assert.equal(calls, 1);
});
test('transport rejection remains visible to the UI and is retained as collection failure', async () => {
  const sandbox = page(async () => { throw new Error('controlled offline'); });
  await assert.rejects(sandbox.fetch('/api/live-design/variants'), /controlled offline/);
  assert.equal(sandbox.__variantWire.done, true);
  assert.match(sandbox.__variantWire.error, /controlled offline/);
});
test('truncation and oversized events retain an explicit collection failure', async () => {
  for (const body of ['{"type":"shell"}\n', 'x'.repeat(524289)]) {
    const sandbox = page(async () => new Response(body));
    const response = await sandbox.fetch('/api/live-design/variants'); await response.text();
    await flush(() => sandbox.__variantWire.done);
    assert.match(sandbox.__variantWire.error, /interrupted|limit/);
    assert.equal(sandbox.__variantWire.outcome, null);
  }
});
test('failed evidence cannot be overwritten by a repeated run or output directory', () => {
  const directory=join(mkdtempSync(join(process.env.FURNITUREOS_EVIDENCE_DIR??tmpdir(),'ticket14-observer-')),'run');
  const save=createTimingEvidence(directory);
  save('failure.json',{error:'retained controlled failure'});
  assert.throws(()=>save('failure.json',{error:'replacement'}),/EEXIST/);
  assert.throws(()=>createTimingEvidence(directory),/EEXIST/);
  assert.equal(JSON.parse(readFileSync(join(directory,'failure.json'))).error,'retained controlled failure');
});
