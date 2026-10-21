import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, copyFile, rename, lstat, unlink, open } from 'node:fs/promises';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { PRODUCT_ASSET_SOURCES } from '../../scripts/asset-pipeline.config.mjs';
import { commonAnchorStyles } from '../../scripts/lib/reviewed-anchor-styles.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { Engine } from './engine.mjs';
import { adapter } from './catalogue.mjs';
import { assertLocalContext, ownRoot, ownedPath, noLinks, digest, hashFile, NATIVE } from './safety.mjs';
import { durableFile } from './store.mjs';
import { LIVING_PROFILE, LIVING_PURPOSE, AGENT_PURPOSE } from './profiles.mjs';

async function exists(file) {
  try { await lstat(file); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; }
}
export async function promotionInventory(engine, { controlledFixture = false } = {}) {
  const s = engine.state;
  assert.equal(s.freeze.profile, LIVING_PROFILE);
  assert(['owner', 'agent'].includes(s.actor), 'Only a real owner or genuine agent review can authorize promotion');
  const agent = s.actor === 'agent';
  assert.equal(s.freeze.purpose, agent ? AGENT_PURPOSE : LIVING_PURPOSE);
  assert.equal(s.evidenceKind, controlledFixture ? 'controlled-automated-owner-state' : agent ? 'genuine-agent-curation' : 'owner', 'Controlled evidence cannot be promoted');
  assert.equal(s.sample.status, 'FINISHED', 'Seed review is pending');
  const report = engine.report();
  assert.equal(report.reviewEvidenceStatus, controlledFixture ? 'UNRUN' : agent ? 'COMPLETED_VALID_AGENT_REVIEW' : 'COMPLETED_VALID_OWNER');
  if (agent) assert.equal(report.ownerEvidenceStatus, 'UNRUN');
  assert((agent ? s.freeze.reviewerIdentity : s.freeze.ownerIdentity)?.trim(), 'Missing review identity');
  assert(s.candidates.every((c) => c.decision), 'Unresolved candidate');
  const accepted = s.candidates.filter((c) => c.decision === 'accepted');
  const entries = [];
  for (const c of accepted) {
    assert(c.selection && !c.error && c.note?.trim(), 'Missing current acceptance or owner notes');
    assert.deepEqual(c.rooms, ['living-room'], 'Living seed promotion accepts explicit Living room tags only');
    const a = s.attempts.find((a) => a.id === c.selection.attemptId);
    assert(a?.status === 'succeeded' && a.evidenceKind === 'real-native-conversion', 'Acceptance must bind native conversion');
    const source = s.freeze.orderedSources.find((p) => p.productId === c.productId);
    const dir = await ownedPath(engine.root, 'attempts', a.id, 'output');
    const raw = await ownedPath(engine.root, 'sources', a.id, source.sourceFile);
    const verified = await verifyProductAssets(dir, source, { sourcePath: raw });
    assert.deepEqual(verified.files, a.files, 'Accepted runtime bytes changed');
    const result = JSON.parse(await readFile(await ownedPath(engine.root, 'attempts', a.id, 'result.json'), 'utf8'));
    assert.deepEqual(result.source, source);
    assert.deepEqual(result.files, a.files);
    assert.equal(result.kind, 'real-native-conversion');
    assert.deepEqual(await hashFile(await ownedPath(engine.root, 'attempts', a.id, 'input.json')), result.input);
    assert.equal(result.tool.archive.sha256, NATIVE.sha256);
    for (const pin of [result.tool.archive, result.tool.binary]) assert.deepEqual(await hashFile(await ownedPath(engine.root, pin.file)), { bytes: pin.bytes, sha256: pin.sha256 });
    const entry = await adapter({ mode: 'project', profile: LIVING_PROFILE, seed: s.freeze.seed, productId: c.productId, styles: c.styles, rooms: c.rooms, manifest: verified.manifest, meshBase: null });
    const reused = PRODUCT_ASSET_SOURCES.some((p) => p.productId === c.productId);
    let publication = verified;
    let directory = dir;
    if (reused) {
      const original = await verifyProductAssets(path.join(REPO_ROOT, 'public/products', c.productId), source);
      assert.deepEqual(original.files, s.freeze.previews[c.productId].files, 'Existing publication changed since owner preview');
      // Historical manifests predate added per-LOD diagnostic fields. Reuse
      // the exact frozen publication, including its manifest, without rewriting
      // it. Every renderable byte must also equal the independently rebuilt
      // acceptance; both manifests have passed the same source-bound validator.
      const runtime = (files) => files.filter((f) => f.file !== 'asset-manifest.json');
      assert.deepEqual(runtime(original.files), runtime(verified.files), 'Reused Product runtime identity changed');
      publication = original;
      directory = path.join(REPO_ROOT, 'public/products', c.productId);
    }
    entries.push({ productId: c.productId, rooms: c.rooms, privateStyleIds: c.styles, files: publication.files, reused, directory, category: entry.product.category });
  }
  assert.deepEqual([...new Set(entries.map((e) => e.category))].sort(), ['chair', 'lamp', 'rug', 'sofa', 'table'], 'Accepted seed must contain all five functional categories');
  const supported = new Set(s.freeze.seed.styleVocabulary.styles.map((s) => s.id));
  assert(commonAnchorStyles(entries).some((id) => supported.has(id)), 'All three sofa/table/chair anchors need a common supported Style');
  return { schemaVersion: 1, version: controlledFixture ? 'CONTROLLED-NOT-OWNER-NOT-PRODUCTION' : 'abo-living-reviewed-v1', profileSha256: s.freeze.seedSha256, reviewActor: s.actor, reviewEvidenceSha256: digest(JSON.stringify(report)), entries };
}

async function install(inventory, transaction, targetRoot) {
  const products = path.join(targetRoot, 'public/products');
  const metadataDir = path.join(targetRoot, 'api/catalogue/providers');
  await mkdir(products, { recursive: true });
  await mkdir(metadataDir, { recursive: true });
  const overlay = await noLinks(path.join(metadataDir, 'abo-living-reviewed.json'));
  const lock = await noLinks(path.join(metadataDir, '.living-promotion.lock'));
  await durableFile(lock, { transaction, version: inventory.version });
  assert(!await exists(overlay), 'Existing living publication; preserve transaction');
  for (const e of inventory.entries.filter((e) => !e.reused)) {
    const target = await noLinks(path.join(products, e.productId));
    await mkdir(target);
    for (const f of e.files) {
      await mkdir(path.dirname(path.join(target, f.file)), { recursive: true });
      await copyFile(path.join(transaction, e.productId, f.file), path.join(target, f.file), 1);
    }
  }
  // Reopen and flush the installed closed inventory before metadata activates it.
  // Staging validation alone is insufficient proof of the installed bytes.
  for (const e of inventory.entries) {
    for (const f of e.files) {
      const target = await noLinks(path.join(products, e.productId, f.file));
      assert.deepEqual(await hashFile(target), { bytes: f.bytes, sha256: f.sha256 }, 'Installed publication changed');
      const handle = await open(target, 'r+');
      try { await handle.sync(); } finally { await handle.close(); }
    }
  }
  const metadata = { ...inventory, entries: inventory.entries.map(({ directory, category, reused, ...e }) => e) };
  const pending = path.join(metadataDir, `.living-${randomUUID()}.pending`);
  await durableFile(pending, metadata);
  assert(!await exists(overlay), 'Publication appeared during apply; preserve staging');
  await rename(pending, overlay);
  await durableFile(path.join(transaction, 'applied.json'), { metadata: await hashFile(overlay), at: new Date().toISOString() });
  await unlink(lock);
}

async function stage(inventory, transaction, sources) {
  for (const e of inventory.entries.filter((e) => !e.reused)) {
    const staged = path.join(transaction, e.productId);
    await mkdir(staged);
    for (const f of e.files) {
      const target = path.join(staged, f.file);
      await mkdir(path.dirname(target), { recursive: true });
      await copyFile(path.join(e.directory, f.file), target);
    }
    assert.deepEqual((await verifyProductAssets(staged, sources.find((p) => p.productId === e.productId))).files, e.files);
  }
}

// This explicit import-only proof seam always stamps invalid-for-production
// metadata and can only install outside every Git checkout. No CLI/env enables it.
export async function applyControlledFixture(engine, destination) {
  const root = await ownRoot(destination);
  const inventory = await promotionInventory(engine, { controlledFixture: true });
  // Materialize the reused baseline in the isolated fixture, never in source.
  // The installed file inventory is complete even though its metadata is
  // explicitly invalid for production.
  for (const e of inventory.entries.filter((e) => e.reused)) {
    for (const f of e.files) {
      const target = await ownedPath(root, 'public/products', e.productId, f.file);
      await mkdir(path.dirname(target), { recursive: true });
      if (await exists(target)) assert.deepEqual(await hashFile(target), { bytes: f.bytes, sha256: f.sha256 });
      else await copyFile(path.join(e.directory, f.file), target, 1);
    }
  }
  const transaction = await ownedPath(engine.root, 'promotions', randomUUID());
  await mkdir(transaction, { recursive: true });
  await durableFile(path.join(transaction, 'dry-run.json'), { ...inventory, fixture: true, target: root });
  await stage(inventory, transaction, engine.state.freeze.orderedSources);
  await install(inventory, transaction, root);
  return { inventory, transaction, root };
}
// All paths are computed from fixed Product identities and a closed validator inventory.
// A failed transaction retains staging and a transaction log; no automatic overwrite/reset.
export async function promoteLiving({ stateDir, preparedDir, ownerIdentity, reviewerIdentity, actor = 'owner', apply = false }) {
  assertLocalContext();
  const engine = await Engine.open({ stateDir, preparedDir, ownerIdentity, reviewerIdentity, profile: LIVING_PROFILE, actor });
  try {
    const inventory = await promotionInventory(engine);
    const overlay = path.join(REPO_ROOT, 'api/catalogue/providers/abo-living-reviewed.json');
    const conflicts = [];
    if (await exists(overlay)) conflicts.push(overlay);
    for (const e of inventory.entries.filter((e) => !e.reused)) {
      const target = await noLinks(path.join(REPO_ROOT, 'public/products', e.productId));
      if (await exists(target)) conflicts.push(target);
    }
    const transaction = await ownedPath(engine.root, 'promotions', randomUUID());
    await mkdir(transaction, { recursive: true });
    await durableFile(path.join(transaction, 'dry-run.json'), { ...inventory, conflicts, apply });
    if (!apply) return { inventory, conflicts, transaction };
    assert.equal(conflicts.length, 0, 'Promotion conflicts; inspect retained dry run');
    await stage(inventory, transaction, engine.state.freeze.orderedSources);
    await install(inventory, transaction, REPO_ROOT);
    return { inventory, conflicts, transaction };
  } finally { await engine.close(); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), options = {};
  const names = { '--state-dir': 'stateDir', '--prepared-dir': 'preparedDir', '--owner-id': 'ownerIdentity', '--reviewer-id': 'reviewerIdentity', '--actor': 'actor' };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--apply') { assert(!options.apply, 'Duplicate --apply'); options.apply = true; continue; }
    const name = names[args[i]];
    assert(name && args[i + 1] && !options[name], 'Use --state-dir <review> --prepared-dir <prepared> --owner-id <identity> OR --actor agent --reviewer-id <identity> [--apply]');
    options[name] = args[++i];
  }
  assert(options.stateDir && options.preparedDir && ['owner', 'agent'].includes(options.actor ?? 'owner'));
  console.log(JSON.stringify(await promoteLiving(options), null, 2));
}
