import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { Engine } from '../engine.mjs';
import { evidenceDir, controlledOutput, controlledRunner, controlledBarrier, operation, waitSettled, lamp } from './helpers.mjs';

function invalid(engine) {
  assert.equal(engine.state.sample.status, 'INVALID');
  const report = engine.report();
  assert.equal(report.ownerEvidenceStatus, 'UNRUN');
  assert.equal(report.timing.validOwnerTiming, false);
  assert.equal(report.estimate, null);
  assert.match(report.timing.invalidReason, /backwards/);
  const times = engine.store.events.filter((e) => e.type !== 'initialized').map((e) => e.at);
  assert(times.every((at, i) => Number.isFinite(at) && (!i || at >= times[i - 1])));
  assert(engine.state.sample.lastTimestamp >= Math.max(...times));
}

test('every timing read detects rollback above the durable watermark without polling journal writes', async (t) => {
  for (const read of ['view', 'report', 'elapsed']) await t.test(read, async () => {
    let now = 10000;
    const root = await evidenceDir(`clock-read-${read}-CONTROLLED`);
    const engine = await Engine.open({ stateDir: root, actor: 'owner', controlled: true, clock: () => now });
    try {
      await operation(engine, { type: 'estimate', remainingCandidates: 100 });
      await operation(engine, { type: 'start' });
      const revision = engine.state.revision, files = await readdir(path.join(root, 'journal'));
      for (let i = 0; i < 200; i++) { now += 10; engine[read](); }
      await engine.queue;
      assert.equal(engine.state.revision, revision);
      assert.deepEqual(await readdir(path.join(root, 'journal')), files);
      // This rollback remains ABOVE the last durable event: only an in-process
      // observation watermark can detect it. Recovery precedes the next mutation.
      now -= 500; engine[read]();
      assert.equal(engine.view().sample.status, 'INVALID');
      now += 5000; await engine.queue;
      invalid(engine);
      assert.equal(engine.store.events.filter((e) => e.type === 'clock-invalid').length, 1);
      for (let i = 0; i < 50; i++) engine[read]();
      await engine.queue;
      assert.equal(engine.state.revision, revision + 1);
      await operation(engine, { type: 'navigate', cursor: 5 });
      assert.equal(engine.view().cursor, 5);
      assert(engine.view().candidates.length === 20);
      await assert.rejects(operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] }), /backwards/);
      await assert.rejects(operation(engine, { type: 'resume' }), /backwards/);
      await engine.close();
      const reopened = await Engine.open({ stateDir: root, actor: 'owner', controlled: true, clock: () => now });
      try {
        await operation(reopened, { type: 'navigate', cursor: 6 });
        assert.equal(reopened.view().cursor, 6);
        assert.equal(reopened.report().sampleStatus, 'INVALID');
        await assert.rejects(operation(reopened, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] }), /only while ACTIVE/);
      } finally { await reopened.close(); }
    } finally { await engine.close(); }
  });
});

test('controlled progress and settlement rollback cannot recover into valid owner timing', async (t) => {
  for (const phase of ['progress', 'settlement']) await t.test(phase, async () => {
    let now = 10000;
    const runner = async (input) => {
      now = 20000; await input.progress('controlled-high-watermark');
      if (phase === 'progress') {
        now = 15000; await input.progress('controlled-rollback'); now = 30000;
      }
      const result = await controlledOutput(input);
      if (phase === 'settlement') now = 15000;
      return result;
    };
    const engine = await Engine.open({ stateDir: await evidenceDir(`clock-${phase}-CONTROLLED`), actor: 'owner', controlled: true, clock: () => now, runner });
    try {
      await operation(engine, { type: 'start' });
      await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
      await operation(engine, { type: 'accept', productId: lamp }); await waitSettled(engine);
      now = 40000;
      invalid(engine);
      assert.equal(engine.state.attempts[0].status, 'succeeded');
      assert(engine.state.attempts[0].durationMs >= 0);
      assert.equal(engine.state.attempts[0].timingUncertain, true);
    } finally { await engine.close(); }
  });
});

async function finishable(engine) {
  await operation(engine, { type: 'estimate', remainingCandidates: 100 });
  await operation(engine, { type: 'start' });
  await operation(engine, { type: 'tags', productId: lamp, styles: ['style-01'], rooms: ['bedroom'] });
  await operation(engine, { type: 'accept', productId: lamp }); await waitSettled(engine);
  for (const c of engine.state.candidates) if (!c.decision) await operation(engine, { type: 'reject', productId: c.productId });
}

test('Finish detects rollback at its post-verification timestamp', async () => {
  let now = 10000;
  const engine = await Engine.open({ stateDir: await evidenceDir('clock-finish-second-read-CONTROLLED'), actor: 'owner', controlled: true, clock: () => now, runner: controlledRunner() });
  try {
    await finishable(engine); now = 20000;
    const verify = engine.verifyAttempt.bind(engine);
    engine.verifyAttempt = async (attempt) => { await verify(attempt); now = 15000; };
    await assert.rejects(operation(engine, { type: 'finish' }), /backwards/);
    now = 30000; await engine.queue; invalid(engine);
    assert.equal(engine.store.events.filter((e) => e.type === 'finish').length, 0);
  } finally { await engine.close(); }
});

test('read-observed rollback during held Finish verification survives recovery and pending snapshots', async () => {
  let now = 10000;
  const gate = controlledBarrier();
  const engine = await Engine.open({ stateDir: await evidenceDir('clock-finish-await-CONTROLLED'), actor: 'owner', controlled: true, clock: () => now, runner: controlledRunner() });
  try {
    await finishable(engine);
    const verify = engine.verifyAttempt.bind(engine);
    engine.verifyAttempt = async (attempt) => { await verify(attempt); await gate.wait(); };
    const finishing = operation(engine, { type: 'finish' });
    // Attach rejection handling immediately while the operation is held.
    const rejected = assert.rejects(finishing, /backwards/);
    await gate.entered;
    now = 20000; engine.view(); now = 15000;
    assert.equal(engine.report().sampleStatus, 'INVALID');
    now = 30000; gate.release(); await rejected; await engine.queue;
    invalid(engine);
  } finally { gate.release(); await engine.close(); }
});

test('a rollback while Finish durable commit is suspended invalidates before acknowledgement', async () => {
  let now = 10000;
  const engine = await Engine.open({ stateDir: await evidenceDir('clock-finish-commit-CONTROLLED'), actor: 'owner', controlled: true, clock: () => now, runner: controlledRunner() });
  try {
    await finishable(engine); now = 20000;
    const commit = engine.store.commit.bind(engine.store);
    engine.store.commit = async (next, event) => {
      const result = await commit(next, event);
      if (event.type === 'finish') {
        now = 15000;
        // Simulate an HTTP report while the final store write has completed but
        // its serialized Finish still owns the active observation scope.
        assert.equal(engine.report().sampleStatus, 'INVALID');
      }
      return result;
    };
    const result = await operation(engine, { type: 'finish' });
    assert.equal(result.state.sample.status, 'INVALID');
    now = 30000; await engine.queue; invalid(engine);
  } finally { await engine.close(); }
});
