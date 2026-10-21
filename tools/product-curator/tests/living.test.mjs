import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, readFile, appendFile } from 'node:fs/promises';
import path from 'node:path';
import { Engine } from '../engine.mjs';
import { freezeInputs } from '../catalogue.mjs';
import { parseArgs } from '../server.mjs';
import { promotionInventory, applyControlledFixture } from '../promote-living.mjs';
import { evidenceDir, operation } from './helpers.mjs';
import { copyCandidate } from '../runtime-copy.mjs';
import { commonAnchorStyles } from '../../../scripts/lib/reviewed-anchor-styles.mjs';

const preparedDir = process.env.TICKET12_PREPARED_DIR;
const options = { profile: 'living-seed-v1', preparedDir, ownerIdentity: 'CONTROLLED-AUTOMATED-NOT-OWNER' };
test('promotion and pipeline share the required sofa/table/chair Style guard', () => {
  const entries = [{ category:'sofa', privateStyleIds:['style-01'] }, { category:'table', privateStyleIds:['style-01'] }, { category:'chair', privateStyleIds:['style-02'] }];
  assert.deepEqual(commonAnchorStyles(entries), []);
  assert.deepEqual(commonAnchorStyles([...entries, { category:'chair', privateStyleIds:['style-01'] }]), ['style-01']);
  assert.deepEqual(commonAnchorStyles(entries.slice(0,2)), []);
});
test('profile is explicit, capped and durably mismatched against legacy/identity', { skip: !preparedDir }, async () => {
  const root = await evidenceDir('living-profile');
  let engine = await Engine.open({ ...options, stateDir: root, actor: 'automated' });
  assert.equal(engine.view().freeze.count, 8);
  assert.equal(engine.report().freeze.denominator, 8);
  assert.equal(engine.state.freeze.reviewImages.length, 6);
  const image=engine.state.freeze.reviewImages[0];
  assert.equal((await engine.reviewImage(image.sha256,image.fileName)).length,image.bytes);
  await assert.rejects(engine.reviewImage(image.sha256,'../ref-01.jpg'), /Unknown frozen/);
  assert.equal(engine.state.freeze.purpose, 'Ticket12 living seed suitability and Style review v1');
  await assert.rejects(operation(engine, { type: 'tags', productId: engine.state.candidates[0].productId, styles: ['style-01'], rooms: ['bedroom','living-room'] }), /known/);
  await operation(engine, { type: 'navigate', cursor: 7 });
  await assert.rejects(operation(engine, { type: 'navigate', cursor: 8 }), /Queue position/);
  await assert.rejects(promotionInventory(engine), /real owner/);
  await engine.close();
  await assert.rejects(Engine.open({ stateDir: root, actor: 'automated' }), /identity|changed/i);
  await assert.rejects(Engine.open({ ...options, ownerIdentity: 'DIFFERENT-OWNER', stateDir: root, actor: 'automated' }), /identity|changed/i);
  engine = await Engine.open({ ...options, stateDir: root, actor: 'automated' });
  assert.equal(engine.state.cursor, 7);
  await engine.close();
  assert.throws(() => parseArgs(['--profile', '../../other']), /invalid/);
  assert.throws(() => parseArgs(['--source-url', 'https://example.com']), /invalid/);
});

test('prepared profile rejects changed output, raw source and unsafe roots', { skip: !preparedDir }, async () => {
  const root = path.join(await evidenceDir('living-tamper'), 'prepared');
  await cp(preparedDir, root, { recursive: true, force: false, errorOnExist: true });
  const freeze = await freezeInputs({ ...options, preparedDir: root });
  const id = freeze.seed.products[0].productId;
  const file = path.join(root, 'preparations', id, 'output', 'lod0.gltf');
  await appendFile(file, ' ');
  await assert.rejects(freezeInputs({ ...options, preparedDir: root }), /byte|changed|mismatch/i);
  const other = path.join(await evidenceDir('living-source-tamper'), 'prepared');
  await cp(preparedDir, other, { recursive: true, force: false, errorOnExist: true });
  await appendFile(path.join(other, 'preparations', id, 'source', freeze.orderedSources[0].sourceFile), 'tamper');
  await assert.rejects(freezeInputs({ ...options, preparedDir: other }), /source bytes mismatch/i);
  await assert.rejects(freezeInputs({ ...options, preparedDir: process.cwd() }), /Git checkout|overlaps/);
});

test('controlled owner decisions, Undo and incomplete review cannot become owner authority', { skip: !preparedDir }, async () => {
  const root = await evidenceDir('living-controlled-owner');
  const engine = await Engine.open({ ...options, stateDir: root, actor: 'owner', controlled: true });
  try {
    await operation(engine, { type: 'start' });
    const productId = engine.state.candidates[0].productId;
    await operation(engine, { type: 'note', productId, note: 'CONTROLLED implementation proof only' });
    await operation(engine, { type: 'reject', productId });
    assert.equal(engine.state.candidates[0].decision, 'rejected');
    await operation(engine, { type: 'undo' });
    assert.equal(engine.state.candidates[0].decision, null);
    await assert.rejects(operation(engine, { type: 'finish' }), /all frozen/);
    await assert.rejects(promotionInventory(engine), /Controlled/);
    await assert.rejects(applyControlledFixture(engine, await evidenceDir('living-incomplete-apply')), /pending/);
    assert.equal(engine.report().ownerEvidenceStatus, 'UNRUN');
  } finally { await engine.close(); }
});

test('living review resumes after shutdown and clock uncertainty preserves decisions without a timed20 gate', { skip: !preparedDir }, async () => {
  const root=await evidenceDir('living-review-resume-CONTROLLED');
  let now=100;
  let engine=await Engine.open({...options,stateDir:root,actor:'owner',controlled:true,clock:()=>now});
  await operation(engine,{type:'start'});
  const productId=engine.state.candidates[0].productId;
  await operation(engine,{type:'note',productId,note:'CONTROLLED-NOT-OWNER test rejection'});
  await operation(engine,{type:'reject',productId});
  await engine.close();
  now=200;
  engine=await Engine.open({...options,stateDir:root,actor:'owner',controlled:true,clock:()=>now});
  try {
    assert.equal(engine.state.sample.status,'PAUSED');
    assert.equal(engine.state.candidates[0].decision,'rejected');
    await operation(engine,{type:'resume'});
    now=150;
    await operation(engine,{type:'note',productId:engine.state.candidates[1].productId,note:'CONTROLLED clock uncertainty is not a suitability gate'});
    await engine.queue;
    assert.equal(engine.state.sample.status,'ACTIVE');
    assert.equal(engine.state.sample.activityTimingUncertain,true);
    assert.equal(engine.report().timing.validOwnerTiming,false);
    assert.equal(engine.report().timing.activeSeconds,null);
    assert.equal(engine.report().ownerEvidenceStatus,'UNRUN');
  } finally {await engine.close();}
});

test('agent actor requires separate identity, explicit lifecycle and controlled runners cannot escalate', { skip: !preparedDir }, async () => {
  const root = await evidenceDir('CONTROLLED-agent-lifecycle');
  const agent = { profile: 'living-seed-v1', preparedDir, actor: 'agent', reviewerIdentity: 'CONTROLLED-AGENT-NOT-REAL-REVIEW', controlled: true, stateDir: root };
  await assert.rejects(Engine.open({ ...agent, profile: 'bedroom20' }), /living profile/);
  await assert.rejects(Engine.open({ ...agent, controlled: false, runner: async () => ({ kind: 'real-native-conversion' }) }), /Injected runners/);
  let engine = await Engine.open(agent);
  assert.equal(engine.state.freeze.ownerIdentity, undefined);
  assert.equal(engine.state.evidenceKind, 'controlled-automated-agent-state');
  assert.match(engine.state.freeze.purpose, /genuine agent/);
  assert.equal(engine.view().candidates, undefined);
  await assert.rejects(operation(engine, { type: 'navigate', cursor: 1 }), /Start or resume/);
  await operation(engine, { type: 'start' });
  await operation(engine, { type: 'pause' });
  await assert.rejects(operation(engine, { type: 'note', productId: engine.state.candidates[0].productId, note: 'CONTROLLED ONLY' }), /ACTIVE/);
  await engine.close();
  await assert.rejects(Engine.open({ ...agent, controlled: false }), /identity|Evidence|evidence/);
  await assert.rejects(Engine.open({ ...agent, reviewerIdentity: 'ANOTHER-REVIEWER' }), /identity|metadata/);
  await assert.rejects(Engine.open({ ...options, stateDir: root, actor: 'owner' }), /identity|metadata/);
  engine = await Engine.open(agent);
  try {
    await operation(engine, { type: 'resume' });
    for (const candidate of engine.state.candidates) {
      await operation(engine, { type: 'note', productId: candidate.productId, note: 'CONTROLLED lifecycle rejection only; no suitability judgment' });
      await operation(engine, { type: 'reject', productId: candidate.productId });
    }
    await operation(engine, { type: 'finish' });
    assert.equal(engine.report().ownerEvidenceStatus, 'UNRUN');
    assert.equal(engine.report().agentEvidenceStatus, 'UNRUN');
    await assert.rejects(operation(engine, { type: 'undo' }), /ACTIVE/);
    await assert.rejects(promotionInventory(engine), /Controlled/);
  } finally { await engine.close(); }
  assert.throws(() => parseArgs(['--actor', 'agent', '--profile', 'living-seed-v1']), /reviewer-id/);
});

test('controlled runtime copies absent candidates, reuses only exact installed bytes and retains mismatches', { skip: !preparedDir }, async () => {
  const freeze = await freezeInputs(options);
  const source = freeze.orderedSources[0], preview = freeze.previews[source.productId];
  const root = await evidenceDir('CONTROLLED-runtime-copy');
  const target = path.join(root, source.productId);
  await copyCandidate(preview, source, target);
  await copyCandidate(preview, source, target);
  await appendFile(path.join(target, 'lod0.gltf'), ' ');
  await assert.rejects(copyCandidate(preview, source, target), /byte|differ|mismatch/i);
});
