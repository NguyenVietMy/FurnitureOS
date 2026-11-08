// Data-only contract shared by local intake, publication and build inventory.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { lstatSync, readFileSync, readdirSync, existsSync } from 'node:fs';
import path from 'node:path';

export const PROFILE = 'catalogue-expansion-v1';
export const INDEX_POLICY = 'catalogue-expansion-index-v1';
export const METADATA_SHA256 = '660f4d01bf817802c4fc664e848af12b72246efdb15324ad1d0d2bce33f54fe9';
export const CATEGORIES = ['bed','nightstand','wardrobe','dresser','chair','sofa','table','rug','lamp'];
export const STYLES = ['style-01','style-02','style-03','style-04','style-05'];
export const canonical = (v) => JSON.stringify(v && typeof v === 'object' ? Array.isArray(v) ? v.map((x) => JSON.parse(canonical(x))) : Object.fromEntries(Object.keys(v).sort().map((k) => [k, JSON.parse(canonical(v[k]))])) : v);
export const sha = (v) => createHash('sha256').update(v).digest('hex');
export const pin = (v) => { assert(typeof v === 'string' && /^[a-f0-9]{64}$/.test(v), 'Invalid SHA256'); return v; };
export const id = (v) => { assert(typeof v === 'string' && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(v) && v.length <= 100, 'Unsafe identity'); return v; };
export function keys(v, required, optional = []) {
  assert(v && typeof v === 'object' && !Array.isArray(v));
  assert(required.every((k) => Object.hasOwn(v, k)) && Object.keys(v).every((k) => [...required,...optional].includes(k)), `Invalid fields; expected ${required}`);
}
export const text = (v) => { assert(typeof v === 'string' && v.trim().length > 0 && v.length <= 4000, 'Nonempty bounded text required'); return v; };
export function selection(v, allowed, minimum = 1) {
  assert(Array.isArray(v) && v.length >= minimum && v.length <= allowed.length && new Set(v).size === v.length && v.every((x) => allowed.includes(x)), 'Unknown/duplicate selection');
}
export function candidate(c) {
  keys(c, ['productId','itemId','modelId','displayName','brand','colour','proposedCategory','sourcePath','sourceUrl','sourceSha256','sourceBytes']);
  id(c.productId);
  for (const s of [c.itemId,c.modelId]) assert(/^[A-Z0-9]{10}$/.test(s));
  for (const s of [c.displayName,c.brand,c.colour]) text(s);
  // A source screener may name the coffee-table role explicitly. This is a
  // proposal only; accepted Product.category still requires reviewed `table`.
  assert([...CATEGORIES,'coffee-table'].includes(c.proposedCategory));
  assert.equal(c.sourcePath, `${c.modelId.at(-1)}/${c.modelId}.glb`);
  assert.equal(c.sourceUrl, `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${c.sourcePath}`);
  pin(c.sourceSha256); assert(Number.isSafeInteger(c.sourceBytes) && c.sourceBytes > 0 && c.sourceBytes <= 100_000_000, 'Source exceeds bounded 100 MB');
  return c;
}
export function intake(v) {
  keys(v, ['schemaVersion','profile','batchId','actor','reviewerIdentity','purpose','metadataSha256','evidenceKind','candidates']);
  assert.equal(v.schemaVersion, 1); assert.equal(v.profile, PROFILE); id(v.batchId);
  assert.equal(v.actor, 'agent'); text(v.reviewerIdentity); text(v.purpose);
  assert(['genuine-agent-curation','technical-only'].includes(v.evidenceKind));
  assert.equal(v.metadataSha256, METADATA_SHA256);
  assert(Array.isArray(v.candidates) && v.candidates.length > 0 && v.candidates.length <= 50);
  v.candidates.forEach(candidate);
  for (const field of ['productId','itemId','modelId','sourcePath','sourceSha256']) assert.equal(new Set(v.candidates.map((c) => c[field])).size, v.candidates.length, `Duplicate ${field}`);
  assert(v.candidates.reduce((n,c) => n+c.sourceBytes,0) <= 1_000_000_000, 'Batch source bytes exceed 1 GB');
  return v;
}
export function functional(d) {
  selection(d.rooms, ['bedroom','living-room']); selection(d.privateStyleIds, STYLES);
  assert(CATEGORIES.includes(d.category));
  const rooms = d.category === 'bed' || ['nightstand','wardrobe','dresser'].includes(d.category) ? ['bedroom'] : ['sofa','table'].includes(d.category) ? ['living-room'] : ['bedroom','living-room'];
  assert(d.rooms.every((r) => rooms.includes(r)), 'Category incompatible with Room Type');
  assert.equal(d.placementClass, d.category === 'rug' ? 'floor-covering' : 'floor-standing');
  selection(d.wallContactFaces, ['back','left','right'], 0);
  assert(Array.isArray(d.accessRegions) && d.accessRegions.length <= 4);
  const faces = new Set();
  for (const a of d.accessRegions) {
    keys(a, ['face','depthM','required','purpose']);
    assert(['front','back','left','right'].includes(a.face) && !faces.has(a.face)); faces.add(a.face);
    assert(a.required === true && Number.isFinite(a.depthM) && a.depthM >= 0.6 && a.depthM <= 2); text(a.purpose);
    assert(!d.wallContactFaces.includes(a.face), 'Wall face conflicts with required access');
  }
  const required = d.category === 'bed' ? ['left','right','front'] : ['lamp','rug'].includes(d.category) ? [] : ['front'];
  assert(required.every((f) => faces.has(f)), 'Missing functional access face');
  if (d.category === 'rug') assert(d.accessRegions.length === 0 && d.wallContactFaces.length === 0);
  return d;
}
export function files(v) {
  assert(Array.isArray(v) && v.length >= 8 && v.length <= 64);
  assert.equal(new Set(v.map((f) => f.file)).size, v.length);
  for (const f of v) {
    keys(f, ['file','bytes','sha256']);
    assert(/^(?:asset-manifest\.json|lod[012]\.(?:bin|gltf)|textures\/[a-zA-Z0-9_.-]+\.ktx2)$/.test(f.file));
    pin(f.sha256); assert(Number.isSafeInteger(f.bytes) && f.bytes > 0);
  }
  assert(['asset-manifest.json',... [0,1,2].flatMap((i) => [`lod${i}.gltf`,`lod${i}.bin`])].every((f) => v.some((x) => x.file === f)));
  assert(v.reduce((n,f) => n + (f.file === 'asset-manifest.json' ? 0 : f.bytes),0) < 5_000_000);
}
export function batch(v) {
  keys(v, ['schemaVersion','profile','batchId','intakeSha256','metadataSha256','review','curatedOn','entries']);
  assert.equal(v.schemaVersion, 1); assert.equal(v.profile, PROFILE); id(v.batchId); pin(v.intakeSha256); assert.equal(v.metadataSha256, METADATA_SHA256);
  keys(v.review, ['actor','reviewerIdentity','purpose','evidenceKind','evidenceSha256']);
  assert.equal(v.review.actor,'agent'); assert.equal(v.review.evidenceKind,'genuine-agent-curation'); text(v.review.reviewerIdentity); text(v.review.purpose); pin(v.review.evidenceSha256);
  assert(/^\d{4}-\d{2}-\d{2}$/.test(v.curatedOn));
  assert(v.entries.length > 0 && v.entries.length <= 50);
  for (const e of v.entries) {
    keys(e, ['record','rooms','files','reviewSha256','conversionSha256']);
    const r = e.record;
    keys(r, ['productId','itemId','displayName','brand','colour','category','placementClass','sourcePath','sourceSha256','sourceBytes','privateStyleIds','wallContactFaces','accessRegions']);
    const modelId = r.sourcePath.split('/')[1]?.replace('.glb','');
    candidate({productId:r.productId,itemId:r.itemId,modelId,displayName:r.displayName,brand:r.brand,colour:r.colour,proposedCategory:r.category,sourcePath:r.sourcePath,sourceUrl:`https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${r.sourcePath}`,sourceSha256:r.sourceSha256,sourceBytes:r.sourceBytes});
    functional({...r,rooms:e.rooms}); files(e.files); pin(e.reviewSha256); pin(e.conversionSha256);
  }
  return v;
}
export function sourceRecord(c) {
  return {productId:c.productId,sourceUrl:c.sourceUrl ?? `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/${c.sourcePath}`,sourceFile:`${c.modelId ?? c.sourcePath.split('/')[1].replace('.glb','')}.glb`,sourceSha256:c.sourceSha256,sourceBytes:c.sourceBytes,sourceFrontAxis:'+z'};
}
export function noLinkedPath(file) {
  let current = path.parse(path.resolve(file)).root;
  for (const p of path.resolve(file).slice(current.length).split(path.sep).filter(Boolean)) { current = path.join(current,p); assert(!lstatSync(current).isSymbolicLink(), 'Linked publication path'); }
  return file;
}
export function readPinned(file, p) {
  const raw = readFileSync(noLinkedPath(file)); assert.equal(raw.length,p.bytes); assert.equal(sha(raw),p.sha256); return raw;
}
export function union(baseRecords, batches) {
  const products = new Set(), items = new Set(), models = new Set(), hashes = new Set(), batchIds = new Set();
  for (const b of batches) { assert(!batchIds.has(b.batchId),'Duplicate batch ID'); batchIds.add(b.batchId); }
  for (const r of [...baseRecords,...batches.flatMap((b) => b.entries.map((e) => e.record))]) {
    for (const [set,value] of [[products,r.productId],[items,r.itemId],[models,r.sourcePath],[hashes,r.sourceSha256]]) { assert(!set.has(value),`Global duplicate identity: ${value}`); set.add(value); }
  }
  return products;
}
export function loadExpansion(root, baseVersion, baseRecords, { assets = true } = {}) {
  const dir = path.join(root,'api/catalogue/providers/expansion'), file = path.join(dir,'index.json');
  try { lstatSync(file); } catch(e) { if(e.code === 'ENOENT') return { version:baseVersion, batches:[], digests:[], entries:[] }; throw e; }
  const raw = readFileSync(noLinkedPath(file)), index = JSON.parse(raw);
  keys(index,['schemaVersion','policyVersion','baseVersion','batches']); assert.equal(index.schemaVersion,1); assert.equal(index.policyVersion,INDEX_POLICY); assert.equal(index.baseVersion,baseVersion);
  assert(Array.isArray(index.batches) && index.batches.length > 0 && index.batches.length <= 100 && new Set(index.batches).size === index.batches.length);
  const batches = index.batches.map((s) => { pin(s); const raw = readFileSync(noLinkedPath(path.join(dir,`${s}.json`))); assert.equal(sha(raw),s); const b = batch(JSON.parse(raw)); assert.equal(raw.toString(),canonical(b)); return b; });
  union(baseRecords,batches);
  const entries = batches.flatMap((b) => b.entries);
  if (assets) for (const e of entries) {
    const productDir = path.join(root,'public/products',e.record.productId);
    const inventory = readdirSync(noLinkedPath(productDir),{recursive:true,withFileTypes:true});
    for(const f of inventory) { assert(!f.isSymbolicLink(),'Linked runtime entry'); if(f.isDirectory()) assert(f.name === 'textures' && path.resolve(f.parentPath) === path.resolve(productDir),'Unknown runtime directory'); }
    const actual = inventory.filter((f) => f.isFile()).map((f) => path.relative(productDir,path.join(f.parentPath,f.name)).replaceAll('\\','/')).sort();
    assert.deepEqual(actual,e.files.map((f) => f.file).sort(), 'Published file union drift');
    e.files.forEach((f) => readPinned(path.join(productDir,f.file),f));
  }
  return {version:`${baseVersion}+expansion-${sha(canonical(index))}`,batches,digests:index.batches,entries};
}
