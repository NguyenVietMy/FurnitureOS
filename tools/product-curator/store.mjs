import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { open, readFile, readdir, rename, mkdir, unlink } from 'node:fs/promises';
import path from 'node:path';
import { clone, digest, ownedPath } from './safety.mjs';

export async function durableFile(file, value) {
  const handle = await open(file, 'wx', 0o600);
  try { await handle.writeFile(`${JSON.stringify(value)}\n`); await handle.sync(); }
  finally { await handle.close(); }
}
async function syncDirectory(dir) {
  // Windows does not provide directory fsync through Node; file FlushFileBuffers
  // plus same-volume rename is used. Every committed file itself is fsynced.
  if (process.platform === 'win32') return;
  const handle = await open(dir, 'r');
  try { await handle.sync(); } finally { await handle.close(); }
}
export class Store {
  static async open(root, initial) {
    const store = new Store();
    store.root = root;
    store.lockPath = await ownedPath(root, 'writer.lock');
    store.owner = { pid: process.pid, id: randomUUID(), started: new Date().toISOString() };
    for (let i = 0; i < 2; i++) {
      try { await durableFile(store.lockPath, store.owner); break; }
      catch (error) {
        if (error.code !== 'EEXIST' || i > 0) throw error;
        const lock = JSON.parse(await readFile(store.lockPath, 'utf8'));
        assert(Number.isInteger(lock.pid) && lock.pid > 0 && typeof lock.id === 'string', 'Invalid writer lock: preserve and recover manually');
        try { process.kill(lock.pid, 0); throw new Error('State directory already has a live writer'); }
        catch (probe) { if (probe.code !== 'ESRCH') throw probe; }
        await rename(store.lockPath, await ownedPath(root, `stale-lock-${randomUUID()}.json`));
      }
    }
    try {
      store.dir = await ownedPath(root, 'journal');
      const initializationPath = await ownedPath(root, 'journal-initialized.json');
      const identity = { schemaVersion: 1, actor: initial.actor, seedSha256: initial.freeze.seedSha256 };
      if (initial.actor === 'agent') Object.assign(identity, { evidenceKind: initial.evidenceKind, reviewerIdentity: initial.freeze.reviewerIdentity, purpose: initial.freeze.purpose });
      let initialized = false;
      try {
        assert.deepEqual(JSON.parse(await readFile(initializationPath, 'utf8')), identity, 'Journal initialization identity changed; preserve and use a fresh workspace');
        initialized = true;
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
      let files;
      try { files = (await readdir(store.dir)).sort(); }
      catch (error) {
        if (error.code !== 'ENOENT') throw error;
        assert(!initialized, 'Initialized journal is missing; preserve bytes and follow README recovery');
        await mkdir(store.dir);
        files = [];
      }
      if (initialized) assert(files.length > 0, 'Initialized journal is empty; preserve bytes and follow README recovery');
      else {
        assert.equal(files.length, 0, 'Missing initialization marker for an existing journal; preserve bytes and follow README recovery');
        // Durable before record zero: an interrupted first initialization also
        // fails closed instead of being silently retried as a fresh store.
        await durableFile(initializationPath, identity);
        await syncDirectory(root);
      }
      assert(files.every((f) => /^\d{10}\.json$/.test(f)), 'Incomplete/unknown journal write: preserve bytes; see README recovery');
      store.events = [];
      store.chain = null;
      for (const [i, file] of files.entries()) {
        assert.equal(file, `${String(i).padStart(10, '0')}.json`, 'Journal gap: preserve and recover');
        await ownedPath(root, 'journal', file);
        const record = JSON.parse(await readFile(path.join(store.dir, file), 'utf8'));
        const { hash, ...payload } = record;
        assert.equal(hash, digest(JSON.stringify(payload)), 'Journal checksum mismatch: preserve and recover');
        assert.equal(payload.previous, store.chain, 'Journal chain mismatch');
        assert.equal(payload.state.revision, i, 'Journal revision mismatch');
        assert.equal(payload.state.schemaVersion, 1, 'Unsupported state version; do not reset');
        assert.equal(payload.state.freeze.seedSha256, initial.freeze.seedSha256, 'Pinned seed identity changed; use a fresh workspace');
        assert.deepEqual(payload.state.freeze, initial.freeze, 'Frozen source/preview metadata identity changed');
        assert.equal(payload.state.actor, initial.actor, 'Actor cannot change for a workspace');
        assert.equal(payload.state.evidenceKind, initial.evidenceKind, 'Evidence kind cannot change for a workspace');
        assert.equal(payload.state.sample.actor, initial.actor, 'Sample actor cannot change for a workspace');
        assert.equal(payload.state.sample.protocol, initial.sample.protocol, 'Frozen timing protocol changed; preserve and use a fresh workspace');
        assert.equal(payload.state.sample.denominator, initial.sample.denominator, 'Frozen sample denominator changed');
        assert(payload.state.candidates.length === initial.candidates.length && payload.state.cursor >= 0 && payload.state.cursor < initial.candidates.length, 'Invalid bounded state');
        store.state = payload.state;
        store.events.push({ revision: i, ...payload.event });
        store.chain = hash;
      }
      if (!files.length) await store.commit(initial, { type: 'initialized', actor: initial.actor, at: Date.now() });
      store.poisoned = false;
      return store;
    } catch (error) { await store.close(); throw error; }
  }
  async commit(state, event) {
    assert(!this.poisoned, 'Prior durable write failed; restart and inspect retained bytes');
    const next = clone(state);
    next.revision = this.events.length;
    const payload = { previous: this.chain, event, state: next };
    const hash = digest(JSON.stringify(payload));
    const file = path.join(this.dir, `${String(next.revision).padStart(10, '0')}.json`);
    const temporary = `${file}.${randomUUID()}.pending`;
    try {
      await durableFile(temporary, { ...payload, hash });
      await rename(temporary, file);
      await syncDirectory(this.dir);
    } catch (error) { this.poisoned = true; throw error; }
    this.state = next;
    this.chain = hash;
    this.events.push({ revision: next.revision, ...event });
    return next;
  }
  async close() {
    if (!this.lockPath) return;
    const lock = JSON.parse(await readFile(this.lockPath, 'utf8'));
    assert.equal(lock.id, this.owner.id, 'Writer ownership lost');
    await unlink(this.lockPath);
    this.lockPath = null;
  }
}
