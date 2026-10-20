import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { fork } from 'node:child_process';
import { createWriteStream } from 'node:fs';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { assetBytes, verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { Store, durableFile } from './store.mjs';
import { ownRoot, ownedPath, digest, clone, hashFile, NATIVE } from './safety.mjs';
import { freezeInputs, catalogue, project } from './catalogue.mjs';
import { LIVING_PROFILE } from './profiles.mjs';

export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const fail = (status, message) => { throw new HttpError(status, message); };
const active = (attempt) => attempt.status === 'running';
const PROTOCOL = '20 pinned existing ABO candidates; fresh tags; explicit pauses only; conversion/retry/undo time included. Active server shutdown invalidates timing. This is re-review, not Catalogue growth.';
export function initialState(freeze, actor, controlled = false) {
  assert(['owner', 'automated', 'agent'].includes(actor));
  assert(actor !== 'agent' || freeze.profile === LIVING_PROFILE, 'Agent curation requires the living profile');
  return {
    schemaVersion: 1, revision: -1, actor, freeze,
    evidenceKind: controlled ? actor === 'agent' ? 'controlled-automated-agent-state' : 'controlled-automated-owner-state' : actor === 'owner' ? 'owner' : actor === 'agent' ? 'genuine-agent-curation' : 'controlled-automated',
    cursor: 0,
    candidates: freeze.seed.products.map((p) => ({ productId: p.productId, styles: [], rooms: [], decision: null, selection: null, error: null })),
    attempts: [], undo: [], operations: {},
    sample: { status: 'NOT_STARTED', protocol: freeze.purpose ?? PROTOCOL, denominator: freeze.seed.products.length, actor, activeMs: 0, segmentStart: null, remainingCandidates: null, lastTimestamp: 0 },
  };
}
export class Engine {
  static async open({ stateDir, actor = 'owner', controlled = false, runner, clock = Date.now, profile, preparedDir, ownerIdentity, reviewerIdentity }) {
    assert(actor !== 'agent' || profile === LIVING_PROFILE, 'Agent curation requires the living profile');
    assert(actor !== 'agent' || !runner || controlled, 'Injected runners require explicit controlled agent evidence');
    assert(profile !== LIVING_PROFILE || actor === 'automated' || !runner || controlled, 'Injected living reviewers require explicit controlled evidence');
    const engine = new Engine();
    engine.root = await ownRoot(stateDir);
    engine.clock = clock;
    engine.runner = runner;
    engine.queue = Promise.resolve();
    engine.closing = false;
    const freeze = await freezeInputs({ profile, preparedDir, ownerIdentity, actor, reviewerIdentity });
    engine.store = await Store.open(engine.root, initialState(freeze, actor, controlled));
    // Initial store creation predates owner timing and uses filesystem wall time.
    // All later engine events and durable sample timestamps bind this watermark.
    engine.clockHighWatermark = Math.max(0, engine.state.sample.lastTimestamp,
      ...engine.store.events.filter((e) => e.type !== 'initialized').map((e) => e.at));
    try {
      assert.equal(engine.state.evidenceKind, initialState(freeze, actor, controlled).evidenceKind, 'Workspace evidence mode changed');
      // Reopen every historically committed selection, including undone ones.
      // An output folder alone can never be promoted to an acceptance.
      for (const attempt of engine.state.attempts.filter((a) => a.status === 'succeeded')) await engine.verifyAttempt(attempt);
      const next = clone(engine.state);
      let changed = false;
      for (const attempt of next.attempts.filter(active)) {
        attempt.status = 'interrupted'; attempt.stage = 'interrupted'; attempt.error = 'Server stopped before durable acceptance. Retry creates a new attempt; retained files are not accepted.';
        attempt.endedAt = engine.observeClock();
        attempt.durationMs = Math.max(0, attempt.endedAt - attempt.startedAt);
        const candidate = next.candidates.find((c) => c.productId === attempt.productId);
        candidate.error = attempt.error;
        changed = true;
      }
      if (actor !== 'automated' && next.sample.status === 'ACTIVE') {
        next.sample.status = next.freeze.profile ? 'PAUSED' : 'INVALID';
        if (next.freeze.profile) next.sample.activityTimingUncertain = true;
        else next.sample.invalidReason = 'Active server downtime/shutdown is uncertain. Timing is invalid; preserve/export this workspace and start a fresh sample.';
        next.sample.segmentStart = null;
        changed = true;
      }
      if (changed) await engine.commit(next, { type: 'restart-recovery', at: engine.observeClock(), actor });
      engine.clockReady = true;
      return engine;
    } catch (error) { await engine.store.close(); throw error; }
  }
  get state() { return this.store.state; }
  get busy() { return this.state.attempts.some(active); }
  observeClock(activeOwner = false) {
    const raw = this.clock();
    assert(Number.isFinite(raw), 'Wall clock must return a finite timestamp');
    if (raw < this.clockHighWatermark && this.state.actor === 'owner' && (activeOwner || this.activeClockScopes > 0 || this.state.sample.status === 'ACTIVE') && !this.clockFault) {
      this.clockFault = { observedAt: raw, highWatermark: this.clockHighWatermark };
      // Reads remain responsive during async validation/commit. Latch the fault
      // immediately, then coalesce its durable transition through the same queue.
      if (this.clockReady) this.serialize(async () => {}).catch((error) => { this.fatal = error; });
    }
    this.clockHighWatermark = Math.max(this.clockHighWatermark, raw);
    return this.clockHighWatermark;
  }
  applyClockFault(next) {
    if (this.clockFault && this.state.freeze.profile) {
      next.sample.activityTimingUncertain = true;
      next.sample.clockDiscontinuity = this.clockFault;
      return next;
    }
    if (this.clockFault && next.sample.status !== 'INVALID') {
      next.sample.status = 'INVALID'; next.sample.segmentStart = null;
      next.sample.invalidReason = 'Wall clock moved backwards; active elapsed time is uncertain. Preserve/export and start a fresh workspace.';
      next.sample.clockDiscontinuity = this.clockFault;
    }
    return next;
  }
  async clockCheckpoint(activeOwner = false) {
    const at = this.observeClock(activeOwner);
    if (this.clockFault && this.state.sample.status !== 'INVALID' && (!this.state.freeze.profile || !this.state.sample.activityTimingUncertain)) {
      const next = this.applyClockFault(clone(this.state));
      next.sample.lastTimestamp = at;
      await this.store.commit(next, { type: this.state.freeze.profile ? 'activity-clock-discontinuity' : 'clock-invalid', at, observation: this.clockFault });
    }
  }
  async commit(next, event) {
    const activeOwner = this.state.actor === 'owner' && this.state.sample.status === 'ACTIVE';
    next.sample.lastTimestamp = this.observeClock();
    this.applyClockFault(next);
    await this.store.commit(next, { ...event, clockDiscontinuity: this.clockFault });
    // A read may observe rollback while fsync/validation is suspended. Do not
    // let a previously prepared ACTIVE/FINISHED snapshot erase that observation.
    await this.clockCheckpoint(activeOwner);
  }
  serialize(task) {
    const pending = this.queue.then(async () => {
      const activeOwner = this.state.actor === 'owner' && this.state.sample.status === 'ACTIVE';
      if (activeOwner) this.activeClockScopes = (this.activeClockScopes ?? 0) + 1;
      try { await this.clockCheckpoint(); return await task(); }
      finally {
        try { await this.clockCheckpoint(activeOwner); }
        finally { if (activeOwner) this.activeClockScopes--; }
      }
    });
    this.queue = pending.catch(() => {});
    return pending;
  }
  canRead() { return this.state.actor === 'automated' || !['NOT_STARTED', 'PAUSED'].includes(this.state.sample.status); }
  requireRead() { if (!this.canRead()) fail(423, this.state.freeze.profile ? 'Start or resume the seed review to view candidate details and Meshes.' : 'Start or resume the owner sample to view candidate details and Meshes.'); }
  requireReview() {
    if (this.state.actor !== 'automated' && this.state.sample.status !== 'ACTIVE') fail(423, 'Review is available only while ACTIVE. Finished/invalid decisions are frozen.');
    if (this.busy) fail(409, 'Acceptance is in flight. Wait for conversion, validation and commit; then try again.');
  }
  elapsed(now = this.observeClock()) {
    const s = this.applyClockFault({ sample: { ...this.state.sample } }).sample;
    return s.activeMs + (s.status === 'ACTIVE' ? Math.max(0, now - s.segmentStart) : 0);
  }
  view() {
    const now = this.observeClock();
    const state = this.state;
    const sample = this.applyClockFault({ sample: { ...state.sample } }).sample;
    const summary = {
      revision: state.revision, actor: state.actor, evidenceKind: state.evidenceKind, protocol: state.sample.protocol,
      sample: { ...sample, elapsedMs: this.elapsed(now) },
      freeze: { count: state.candidates.length, purpose: state.freeze.purpose, ownerIdentity: state.freeze.ownerIdentity, reviewerIdentity: state.freeze.reviewerIdentity, seedSha256: state.freeze.seedSha256, seedBytes: state.freeze.seedBytes },
      busy: this.busy,
    };
    if (!this.canRead()) return summary;
    return { ...summary, cursor: state.cursor, candidates: state.candidates.map((c) => this.candidateView(c)), attempts: state.attempts, history: this.store.events, canUndo: state.undo.length > 0, styles: state.freeze.seed.styleVocabulary.styles, reviewImages: state.freeze.reviewImages };
  }
  candidateView(candidate) {
    const record = this.state.freeze.seed.products.find((p) => p.productId === candidate.productId);
    const preview = this.state.freeze.previews[candidate.productId];
    const base = candidate.selection ? `/mesh/attempt/${candidate.selection.attemptId}` : `/mesh/original/${preview.identity}/${candidate.productId}`;
    return { ...candidate, record, dimensions: candidate.selection?.entry.product.dimensionsM ?? Object.fromEntries(['widthM', 'heightM', 'depthM'].map((key, i) => [key, preview.manifest.normalization.bounds.size[i]])), previewUrl: `${base}/lod0.gltf` };
  }
  async verifyAttempt(attempt) {
    const dir = await ownedPath(this.root, 'attempts', attempt.id, 'output');
    const expected = this.state.freeze.orderedSources.find((p) => p.productId === attempt.productId);
    const sourcePath = this.state.freeze.profile ? await ownedPath(this.root, 'sources', attempt.id, expected.sourceFile) : undefined;
    const verified = await verifyProductAssets(dir, expected, { sourcePath });
    this.observeClock();
    assert.deepEqual(verified.files, attempt.files, `Committed attempt ${attempt.id} bytes changed; preserve and recover`);
    const projected = await project(this.state.freeze, { ...this.state.candidates.find((c) => c.productId === attempt.productId), styles: attempt.styles, rooms: attempt.rooms }, attempt, verified.manifest);
    this.observeClock();
    assert.deepEqual(projected, attempt.entry, 'Committed Catalogue entry changed');
    if (this.state.actor === 'agent' && this.state.evidenceKind === 'genuine-agent-curation') await this.verifyNative(attempt, verified);
    return verified;
  }
  async verifyNative(attempt, verified) {
    const result = JSON.parse(await readFile(await ownedPath(this.root, 'attempts', attempt.id, 'result.json'), 'utf8'));
    assert.equal(result.kind, 'real-native-conversion', 'Genuine acceptance requires real native evidence');
    assert.equal(result.attemptId, attempt.id);
    assert.deepEqual(result.source, this.state.freeze.orderedSources.find((s) => s.productId === attempt.productId));
    assert.deepEqual(result.files, verified.files);
    assert.deepEqual(result.input, await hashFile(await ownedPath(this.root, 'attempts', attempt.id, 'input.json')));
    assert.equal(result.tool.archive.sha256, NATIVE.sha256);
    for (const pin of [result.tool.archive, result.tool.binary]) assert.deepEqual(await hashFile(await ownedPath(this.root, pin.file)), { bytes: pin.bytes, sha256: pin.sha256 });
    return result;
  }
  async mutate(operation) {
    this.observeClock();
    // Fast rejection only (never a transition) keeps Pause actionable even
    // while the serialized commit is waiting for validation or durable I/O.
    if (operation?.type === 'pause' && this.state.actor === 'owner' && this.state.sample.status === 'ACTIVE' && this.busy) fail(409, 'Cannot pause during acceptance/validation/commit. Active time continues. Wait, then pause again.');
    const result = await this.serialize(async () => {
      if (this.closing) fail(503, 'Server is shutting down; retry after restart.');
      if (this.clockFault && !this.state.freeze.profile && operation?.type !== 'navigate') fail(409, 'Wall clock moved backwards; timing is invalid. Preserve/export this workspace.');
      assert(operation && typeof operation === 'object' && !Array.isArray(operation), 'Expected operation object');
      const allowed = ['opId', 'revision', 'type', 'productId', 'styles', 'rooms', 'cursor', 'remainingCandidates', 'note'];
      if (Object.keys(operation).some((key) => !allowed.includes(key))) fail(400, 'Unknown mutation field');
      if (!/^[a-zA-Z0-9-]{8,80}$/.test(operation.opId ?? '') || !Number.isInteger(operation.revision)) fail(400, 'Stable operation ID and integer expected revision required');
      const fingerprint = digest(JSON.stringify(operation));
      const replay = this.state.operations[operation.opId];
      if (replay) {
        if (replay.fingerprint !== fingerprint) fail(409, 'Operation ID was reused with different content');
        return { replayed: true };
      }
      // Progress events can advance revision immediately after Accept. Busy
      // Pause must still explain that active timing continues, even when the
      // client has not yet received that progress revision.
      if (operation.type === 'pause' && this.state.actor === 'owner' && this.state.sample.status === 'ACTIVE' && this.busy) fail(409, 'Cannot pause during acceptance/validation/commit. Active time continues. Wait, then pause again.');
      if (operation.revision !== this.state.revision) fail(409, 'State changed in another tab. Reload current state and retry deliberately.');
      const next = clone(this.state);
      const now = this.observeClock();
      let candidate, undo;
      if (['tags', 'accept', 'reject', 'retry', 'note'].includes(operation.type)) {
        candidate = next.candidates.find((c) => c.productId === operation.productId);
        if (!candidate) fail(400, next.freeze.profile ? 'Candidate must belong to the frozen profile' : 'Candidate must be one of the frozen 20');
      }
      let launch;
      switch (operation.type) {
        case 'note':
          this.requireReview();
          if (candidate.decision) fail(409, 'Undo the decision before changing review notes.');
          if (typeof operation.note !== 'string' || operation.note.length > 2000) fail(400, 'Review note must be at most 2000 characters.');
          undo = { candidate: clone(candidate), cursor: next.cursor };
          candidate.note = operation.note;
          break;
        case 'tags': {
          this.requireReview();
          if (candidate.decision) fail(409, 'Undo the decision before editing its tags.');
          const known = next.freeze.seed.styleVocabulary.styles.map((s) => s.id);
          if (!Array.isArray(operation.styles) || !Array.isArray(operation.rooms) || !operation.styles.every((s) => known.includes(s)) || !operation.rooms.every((s) => (next.freeze.profile ? ['living-room'] : ['bedroom', 'living-room']).includes(s)) || new Set(operation.styles).size !== operation.styles.length || new Set(operation.rooms).size !== operation.rooms.length) fail(400, 'Choose unique known Styles and Room Types.');
          undo = { candidate: { productId: candidate.productId, styles: clone(candidate.styles), rooms: clone(candidate.rooms) }, cursor: next.cursor };
          candidate.styles = operation.styles; candidate.rooms = operation.rooms;
          break;
        }
        case 'navigate':
          this.requireRead();
          if (this.state.actor !== 'automated' && this.state.sample.status === 'PAUSED') fail(423, 'Resume before navigating');
          if (!Number.isInteger(operation.cursor) || operation.cursor < 0 || operation.cursor >= next.candidates.length) fail(400, next.freeze.profile ? 'Queue position must be within the frozen queue' : 'Queue position must be 0–19');
          // Navigation remains available during conversion; decisions never auto-accept.
          next.cursor = operation.cursor;
          break;
        case 'accept':
        case 'retry': {
          this.requireReview();
          if (candidate.decision) fail(409, 'Undo the final decision before accepting again.');
          if (operation.type === 'retry' && !candidate.error) fail(409, 'There is no failed/interrupted acceptance to retry.');
          if (next.freeze.profile && next.actor !== 'automated' && !candidate.note?.trim()) fail(422, 'Record suitability, Mesh limitations and Style judgment before acceptance.');
          if (!candidate.styles.length || !candidate.rooms.length) fail(422, 'Select at least one Style and one Room Type before accepting.');
          const attempt = { id: randomUUID(), productId: candidate.productId, status: 'running', stage: 'queued', startedAt: now, styles: clone(candidate.styles), rooms: clone(candidate.rooms), retry: operation.type === 'retry' };
          const dir = await ownedPath(this.root, 'attempts', attempt.id);
          await mkdir(path.dirname(dir), { recursive: true });
          await mkdir(dir);
          await durableFile(path.join(dir, 'input.json'), { freeze: next.freeze, candidate, attempt });
          next.attempts.push(attempt);
          candidate.error = null;
          launch = { attempt, candidate: clone(candidate), dir };
          break;
        }
        case 'reject':
          this.requireReview();
          if (next.freeze.profile && next.actor !== 'automated' && !candidate.note?.trim()) fail(422, 'Record a rejection reason before deciding this candidate.');
          if (candidate.decision) fail(409, 'Undo the final decision first.');
          undo = { candidate: clone(candidate), cursor: next.cursor };
          candidate.decision = 'rejected'; candidate.selection = null; candidate.error = null;
          next.cursor = (next.candidates.indexOf(candidate) + 1) % next.candidates.length;
          break;
        case 'undo': {
          this.requireReview();
          const previous = next.undo.pop();
          if (!previous) fail(409, 'There is no reversible tag or decision event.');
          const index = next.candidates.findIndex((c) => c.productId === previous.candidate.productId);
          if (previous.type === 'tags') {
            // Attempt failure/interruption is independent of reversible tagging.
            next.candidates[index].styles = previous.candidate.styles;
            next.candidates[index].rooms = previous.candidate.rooms;
          } else next.candidates[index] = previous.candidate;
          // Return to the affected candidate; navigation itself is never undone.
          next.cursor = index;
          break;
        }
        case 'start':
          if (next.actor === 'automated' || next.sample.status !== 'NOT_STARTED') fail(409, 'Only an unstarted review can Start.');
          next.sample.status = 'ACTIVE'; next.sample.startedAt = now; next.sample.segmentStart = now;
          break;
        case 'pause':
          if (next.actor === 'automated' || next.sample.status !== 'ACTIVE') fail(409, 'Only an ACTIVE review can Pause.');
          if (this.busy) fail(409, 'Cannot pause during acceptance/validation/commit. Active time continues. Wait, then pause again.');
          next.sample.activeMs += now - next.sample.segmentStart; next.sample.segmentStart = null; next.sample.status = 'PAUSED';
          break;
        case 'resume':
          if (next.actor === 'automated' || next.sample.status !== 'PAUSED') fail(409, 'Only a PAUSED review can Resume.');
          next.sample.status = 'ACTIVE'; next.sample.segmentStart = now;
          break;
        case 'finish':
          if (next.actor === 'automated' || next.sample.status !== 'ACTIVE') fail(409, 'Only an ACTIVE review can Finish.');
          if (this.busy || next.candidates.some((c) => !c.decision || (c.decision === 'accepted' && (!c.selection || c.error)))) fail(422, next.freeze.profile ? 'Finish requires all frozen final decisions and no active or unresolved acceptance.' : 'Finish requires 20 final decisions and no active or unresolved acceptance.');
          for (const c of next.candidates.filter((c) => c.decision === 'accepted')) await this.verifyAttempt(next.attempts.find((a) => a.id === c.selection.attemptId));
          next.sample.finishedAt = this.observeClock();
          next.sample.activeMs += next.sample.finishedAt - next.sample.segmentStart; next.sample.segmentStart = null; next.sample.status = 'FINISHED';
          break;
        case 'estimate':
          if (next.freeze.profile) fail(400, 'Living seed review is a separate purpose, not a timed20 inventory estimate.');
          if (next.actor !== 'owner' || ['FINISHED', 'INVALID'].includes(next.sample.status)) fail(409, 'Set the remaining-candidate estimate before finishing the owner sample.');
          if (operation.remainingCandidates !== null && (!Number.isSafeInteger(operation.remainingCandidates) || operation.remainingCandidates < 0 || operation.remainingCandidates > 1_000_000)) fail(400, 'Enter a nonnegative remaining candidate count or leave it absent.');
          if (this.busy) fail(409, 'Wait for acceptance before editing sample inputs.');
          next.sample.remainingCandidates = operation.remainingCandidates;
          break;
        default: fail(400, 'Unknown mutation type');
      }
      if (undo) next.undo.push({ ...undo, type: operation.type, revision: this.state.revision + 1 });
      const at = this.observeClock();
      if (this.clockFault && !next.freeze.profile && operation.type !== 'navigate') {
        await this.clockCheckpoint();
        fail(409, 'Wall clock moved backwards; timing is invalid. Preserve/export this workspace.');
      }
      next.operations[operation.opId] = { fingerprint };
      await this.commit(next, { type: operation.type, at, actor: next.actor, productId: candidate?.productId ?? null, opId: operation.opId, tags: operation.type === 'tags' ? { styles: candidate.styles, rooms: candidate.rooms } : undefined });
      if (launch) this.launch(launch);
      return {};
    });
    return { ...result, state: this.view() };
  }
  launch(input) {
    let lastFailure;
    const update = (stage) => this.serialize(async () => {
      const next = clone(this.state), attempt = next.attempts.find((a) => a.id === input.attempt.id);
      if (!active(attempt)) return;
      attempt.stage = stage;
      await this.commit(next, { type: 'attempt-stage', attemptId: attempt.id, stage, at: this.observeClock() });
    });
    const settle = (result, error, stage) => this.serialize(async () => {
      const next = clone(this.state), attempt = next.attempts.find((a) => a.id === input.attempt.id);
      if (!active(attempt)) return;
      const candidate = next.candidates.find((c) => c.productId === attempt.productId);
      if (!error) {
        try {
          const source = next.freeze.orderedSources.find((s) => s.productId === candidate.productId);
          const sourcePath = next.freeze.profile ? await ownedPath(this.root, 'sources', attempt.id, source.sourceFile) : undefined;
          const verified = await verifyProductAssets(path.join(input.dir, 'output'), source, { sourcePath });
          this.observeClock();
          assert.deepEqual(verified.files, result.files, 'Worker output hash mismatch');
          const entry = await project(next.freeze, candidate, attempt, verified.manifest);
          this.observeClock();
          assert.deepEqual(entry, result.entry, 'Worker neutral entry mismatch');
          if (next.actor === 'agent' && next.evidenceKind === 'genuine-agent-curation') {
            assert.equal(result.kind, 'real-native-conversion', 'Genuine acceptance requires real native evidence');
            assert.deepEqual(await this.verifyNative(attempt, verified), result, 'Native result identity changed');
          }
          attempt.files = verified.files; attempt.entry = entry; attempt.evidenceKind = result.kind;
          next.undo.push({ candidate: clone(candidate), cursor: next.cursor, type: 'accept', revision: next.revision + 1 });
          candidate.decision = 'accepted'; candidate.selection = { attemptId: attempt.id, entry }; candidate.error = null;
          next.cursor = (next.candidates.indexOf(candidate) + 1) % next.candidates.length;
        } catch (validation) { error = validation; stage = 'commit-validation'; }
      }
      attempt.endedAt = this.observeClock(); attempt.durationMs = Math.max(0, attempt.endedAt - attempt.startedAt);
      if (this.clockFault) attempt.timingUncertain = true;
      attempt.status = error ? 'failed' : 'succeeded'; attempt.stage = error ? stage ?? 'worker' : 'committed';
      attempt.error = error ? String(error.message ?? error) : null;
      if (error) candidate.error = `Attempt failed at ${attempt.stage}: ${attempt.error}. Retry retains all files.`;
      await this.commit(next, { type: error ? 'attempt-failed' : 'accepted', attemptId: attempt.id, productId: candidate.productId, stage: attempt.stage, error: attempt.error, at: attempt.endedAt });
    });
    if (this.runner) {
      this.work = Promise.resolve().then(() => this.runner({ ...input, root: this.root, freeze: this.state.freeze, progress: update })).then((result) => settle(result), (error) => settle(null, error, error.stage)).catch((error) => { this.fatal = error; });
      return;
    }
    const log = createWriteStream(path.join(input.dir, 'worker.log'), { flags: 'wx' });
    this.child = fork(path.join(REPO_ROOT, 'tools/product-curator/worker.mjs'), [this.root, input.attempt.id], { cwd: REPO_ROOT, stdio: ['ignore', 'pipe', 'pipe', 'ipc'], windowsHide: true });
    this.child.stdout.pipe(log, { end: false }); this.child.stderr.pipe(log, { end: false });
    let result;
    this.child.on('message', (message) => {
      if (message.type === 'stage') update(message.stage).catch((error) => { this.fatal = error; });
      if (message.type === 'failure') lastFailure = message;
      if (message.type === 'result') result = message.evidence;
    });
    this.work = new Promise((resolve) => {
      this.child.on('error', (error) => { lastFailure = { error: error.message, stage: 'spawn' }; });
      this.child.on('close', (code) => {
        log.end(); this.child = null;
        settle(result, code !== 0 || !result ? new Error(lastFailure?.error ?? `Worker exited ${code} without validated result`) : null, lastFailure?.stage).catch((error) => { this.fatal = error; }).finally(resolve);
      });
    });
  }
  async entries(query = {}) {
    this.requireRead();
    // Hash binding is rechecked before reads, not only on startup.
    for (const c of this.state.candidates.filter((c) => c.selection)) await this.verifyAttempt(this.state.attempts.find((a) => a.id === c.selection.attemptId));
    return catalogue(this.state.candidates.flatMap((c) => c.selection ? [c.selection.entry] : []), query);
  }
  async mesh(kind, identity, productId, file) {
    this.requireRead();
    let dir, files;
    if (kind === 'original') {
      const preview = this.state.freeze.previews[productId];
      if (!preview || preview.identity !== identity) fail(404, 'Unknown pinned preview identity');
      dir = preview.directory ?? path.join(REPO_ROOT, 'public/products', productId); files = preview.files;
    } else {
      const attempt = this.state.attempts.find((a) => a.id === identity && a.status === 'succeeded');
      if (!attempt) fail(404, 'Unknown committed attempt');
      dir = await ownedPath(this.root, 'attempts', identity, 'output'); files = attempt.files;
    }
    const record = files.find((f) => f.file === file);
    if (!record) fail(404, 'Asset is not in the validated manifest');
    const bytes = await assetBytes(dir, file);
    assert.equal(bytes.length, record.bytes, 'Asset bytes changed'); assert.equal(digest(bytes), record.sha256, 'Asset hash changed');
    return bytes;
  }
  async reviewImage(identity, file) {
    this.requireRead();
    const record = this.state.freeze.reviewImages?.find((r) => r.sha256 === identity && r.fileName === file);
    if (!record || !/^ref-0[1-6]\.jpg$/.test(file)) fail(404, 'Unknown frozen review image');
    const bytes = await readFile(path.join(REPO_ROOT, 'public/style-references', file));
    assert.equal(bytes.length, record.bytes, 'Review image bytes changed');
    assert.equal(digest(bytes), record.sha256, 'Review image hash changed');
    return bytes;
  }
  report() {
    const now = this.observeClock();
    const s = this.applyClockFault({ ...this.state, sample: { ...this.state.sample } });
    const accepted = s.candidates.filter((c) => c.decision === 'accepted' && c.selection).length;
    const rejected = s.candidates.filter((c) => c.decision === 'rejected').length;
    const valid = s.actor === 'owner' && s.evidenceKind !== 'controlled-automated-owner-state' && s.sample.status === 'FINISHED' && !this.activeClockScopes;
    const validAgent = s.actor === 'agent' && s.evidenceKind === 'genuine-agent-curation' && s.sample.status === 'FINISHED' && !this.activeClockScopes;
    const seconds = this.elapsed(now) / 1000;
    const rate = accepted ? seconds / accepted : null;
    return {
      schemaVersion: 1, actor: s.actor, evidenceKind: s.evidenceKind, ownerEvidenceStatus: valid ? 'COMPLETED_VALID_OWNER' : 'UNRUN', agentEvidenceStatus: validAgent ? 'COMPLETED_VALID_AGENT_REVIEW' : 'UNRUN', reviewEvidenceStatus: valid ? 'COMPLETED_VALID_OWNER' : validAgent ? 'COMPLETED_VALID_AGENT_REVIEW' : 'UNRUN', sampleStatus: s.sample.status,
      protocol: s.sample.protocol, purpose: s.freeze.purpose, ownerIdentity: s.freeze.ownerIdentity, reviewerIdentity: s.freeze.reviewerIdentity, freeze: { seedSha256: s.freeze.seedSha256, seedBytes: s.freeze.seedBytes, orderedSources: s.freeze.orderedSources, denominator: s.candidates.length, referenceManifestSha256: s.freeze.referenceManifestSha256, reviewImageInventory: s.freeze.reviewImages?.map(({ id, sha256, bytes }) => ({ id, sha256, bytes })) },
      timing: { ...s.sample, activeSeconds: s.freeze.profile ? null : seconds, secondsPerAccepted: s.freeze.profile ? null : rate, pipelineWaitsIncluded: true, validOwnerTiming: valid && !s.freeze.profile, activityTimingIsAcceptanceGate: !s.freeze.profile },
      counts: { accepted, rejected, unresolved: s.candidates.length - accepted - rejected, failures: s.attempts.filter((a) => ['failed', 'interrupted'].includes(a.status)).length, retries: s.attempts.filter((a) => a.retry).length, undo: this.store.events.filter((e) => e.type === 'undo').length },
      yield: accepted / s.candidates.length,
      estimate: valid && s.sample.remainingCandidates !== null ? { remainingCandidates: s.sample.remainingCandidates, acceptedProducts: s.sample.remainingCandidates * accepted / 20, activeSeconds: s.sample.remainingCandidates * seconds / 20, sampleSize: 20, reviewedDenominator: 20, uncertainty: 'Small selected re-review sample; existing source identities, not a random inventory sample or proof of Catalogue growth.' } : null,
      candidates: s.candidates, attempts: s.attempts, history: this.store.events,
      note: s.freeze.profile ? 'Living seed review is a separate suitability purpose. Historical Ticket11 owner20 is complete; controlled work here supplies no owner judgment.' : valid ? 'Owner active time includes failures, waits, retries and undo. Zero accepted means seconds per accepted is undefined.' : 'No numeric result is completed owner evidence. Controlled automated results are implementation proof only. Real owner sample remains UNRUN.',
    };
  }
  async close() {
    this.closing = true;
    if (this.child) this.child.kill();
    if (this.work) await this.work;
    await this.queue;
    this.clockReady = false;
    await this.clockCheckpoint();
    await this.store.close();
  }
}
