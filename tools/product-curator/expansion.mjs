// Separate expansion protocol. Never opens or changes an owner20/Living journal.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { readFile, mkdir, copyFile, lstat, open, readdir } from 'node:fs/promises';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { intake, functional, keys, pin, text, canonical, sha, sourceRecord } from '../../scripts/lib/expansion-contract.mjs';
import { buildProduct } from '../../scripts/build-product-assets.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { assertLocalContext, ownRoot, ownedPath, noLinks, noGitAncestor, hashFile, nativeTool, NATIVE } from './safety.mjs';
import { durableFile, Store } from './store.mjs';
import {selfContainedGlb} from '../../scripts/lib/source-glb.mjs';

export const MAX_WORKSPACE_BYTES = 4_000_000_000;
async function workspaceBudget(root) {
  let bytes=0,count=0;
  await noLinks(root);
  // Names come from directory enumeration, never manifest/user path fields.
  const walk=async(dir)=>{for(const f of await readdir(dir,{withFileTypes:true})) {assert(!f.isSymbolicLink() && (f.isDirectory() || f.isFile()),'Linked/unsupported workspace entry');const file=path.join(dir,f.name);if(f.isDirectory()) await walk(file);else {bytes+=(await lstat(file)).size;count++;assert(bytes<=MAX_WORKSPACE_BYTES && count<=25_000,'Expansion workspace disk/file budget reached; preserve and use a new bounded batch');}}};
  await walk(root);return {bytes,files:count,limitBytes:MAX_WORKSPACE_BYTES};
}

export async function externalFile(file) { const p = await noLinks(file); await noGitAncestor(p); assert((await lstat(p)).isFile()); return p; }
export async function references() {
  const file = path.join(REPO_ROOT,'api/live-reference-manifest.json'), raw = await readFile(file), manifest = JSON.parse(raw);
  for (const r of manifest.images) { assert(/^ref-0[1-6]\.jpg$/.test(r.fileName)); assert.deepEqual(await hashFile(path.join(REPO_ROOT,'public/style-references',r.fileName)),{bytes:r.bytes,sha256:r.sha256}); }
  return {sha256:sha(raw),images:manifest.images};
}
export class Expansion {
  static async open({stateDir, manifest, metadataFile}) {
    assertLocalContext(); const root = await ownRoot(stateDir);
    const raw = await readFile(await externalFile(manifest)); assert(raw.length <= 200_000,'Intake manifest too large');
    const proposal = intake(JSON.parse(raw));
    if (proposal.evidenceKind === 'genuine-agent-curation') {
      assert(metadataFile,'Genuine expansion requires the pinned official JSONL --metadata-file');
      const metadata = await readFile(await externalFile(metadataFile));
      assert.equal(sha(metadata),proposal.metadataSha256,'Official metadata digest mismatch');
      const needed = new Set(proposal.candidates.map((c)=>`${c.itemId}/${c.modelId}`));
      for(const line of metadata.toString('utf8').split(/\r?\n/)) if(line.trim()) { const r=JSON.parse(line); needed.delete(`${r.item_id}/${r['3dmodel_id']}`); }
      assert.equal(needed.size,0,'Source item/model pair is absent from official metadata');
    }
    const freeze = { profile:proposal.profile, seedSha256:sha(raw), proposal, references:await references(), reviewerIdentity:proposal.reviewerIdentity, purpose:proposal.purpose };
    const initial = {schemaVersion:1,revision:0,actor:'agent',evidenceKind:proposal.evidenceKind,freeze,sample:{actor:'agent',protocol:'expansion-review-v1-no-owner-timing',denominator:proposal.candidates.length},cursor:0,candidates:proposal.candidates.map((c) => ({productId:c.productId,preparation:null,decision:null})),attempts:[],observations:[],operations:[]};
    const store = await Store.open(root,initial), engine = new Expansion(); Object.assign(engine,{root,store});
    try { await engine.verifyAcknowledged(); return engine; } catch (e) { await store.close(); throw e; }
  }
  get state() { return this.store.state; }
  source(productId) { const c = this.state.freeze.proposal.candidates.find((c) => c.productId === productId); assert(c,'Unknown candidate'); return c; }
  async commit(next,event) { return this.store.commit(next,{...event,at:new Date().toISOString()}); }
  async verifyPreparation(c) {
    const a = c.preparation; assert(a,'Mesh has not been prepared');
    const dir = await ownedPath(this.root,'attempts',a.id);
    assert.deepEqual(await hashFile(path.join(dir,'result.json')),a.result,'Acknowledged result changed');
    const result = JSON.parse(await readFile(path.join(dir,'result.json'),'utf8'));
    assert.equal(result.kind,'real-native-conversion');
    assert.deepEqual(result.source,sourceRecord(this.source(c.productId)));
    assert.deepEqual(await hashFile(await ownedPath(this.root,'attempts',a.id,'input.json')),result.input);
    assert.equal(result.tool.archive.sha256,NATIVE.sha256);
    for (const f of [result.tool.archive,result.tool.binary]) assert.deepEqual(await hashFile(await ownedPath(this.root,f.file)),{bytes:f.bytes,sha256:f.sha256});
    const rawPath=path.join(dir,'source',result.source.sourceFile);await selfContainedGlb(rawPath);
    const verified = await verifyProductAssets(path.join(dir,'output'),result.source,{sourcePath:rawPath});
    assert.deepEqual(verified.files,result.files); assert.deepEqual(a.files,result.files);
    return { ...verified, directory:path.join(dir,'output'), result };
  }
  async verifyAcknowledged() {
    assert.equal(this.state.evidenceKind,this.state.freeze.proposal.evidenceKind);
    for (const c of this.state.candidates) if (c.preparation) await this.verifyPreparation(c);
    for (const o of this.state.observations) assert.deepEqual(await hashFile(await ownedPath(this.root,'evidence',o.file)),o.pin,'Review evidence drift');
    for (const a of this.state.attempts.filter((a)=>a.failure)) assert.deepEqual(await hashFile(await ownedPath(this.root,'attempts',a.id,'failure.json')),a.failure,'Technical failure receipt drift');
    for (const c of this.state.candidates) if (c.decision) this.validateDecision(c.productId,c.decision);
  }
  async prepare({sourceDir, acquire = false, productId}) {
    if (sourceDir) { sourceDir = await noLinks(sourceDir); await noGitAncestor(sourceDir); }
    assert(sourceDir || acquire,'Specify external --source-dir or explicit --acquire');
    const selected=preparationCandidates(this.state.candidates,productId);
    const tool = await nativeTool(this.root);
    for (const c of selected) {
      if (c.preparation || c.decision?.decision === 'rejected') continue;
      await workspaceBudget(this.root);
      const source = sourceRecord(this.source(c.productId)), attemptId = randomUUID();
      const dir = await ownedPath(this.root,'attempts',attemptId); await mkdir(path.join(dir,'source'),{recursive:true});
      let next = structuredClone(this.state); next.attempts.push({id:attemptId,productId:c.productId,status:'started'}); await this.commit(next,{type:'preparation-started',attemptId});
      try {
        const rawPath = path.join(dir,'source',source.sourceFile);
        if (sourceDir) await copyFile(await externalFile(path.join(sourceDir,source.sourceFile)),rawPath,1);
        else {
          const response = await fetch(source.sourceUrl,{redirect:'error',signal:AbortSignal.timeout(120_000)}); assert(response.ok,`Source HTTP ${response.status}`);
          const h = await open(rawPath,'wx'); let size = 0;
          try { for await (const chunk of response.body) { size += chunk.length; assert(size <= source.sourceBytes,'Download exceeds declared source bytes'); await h.write(chunk); } await h.sync(); } finally { await h.close(); }
        }
        assert.deepEqual(await hashFile(rawPath),{bytes:source.sourceBytes,sha256:source.sourceSha256});
        await selfContainedGlb(rawPath);
        await durableFile(path.join(dir,'input.json'),{source,tool:tool.evidence,intakeSha256:this.state.freeze.seedSha256});
        await buildProduct(source,{bin:tool.bin,sourceDir:path.join(dir,'source'),workDir:path.join(dir,'work'),outputDir:path.join(dir,'output'),nativeTimeoutMs:120_000,progress:async()=>{await workspaceBudget(this.root);}});
        const verified = await verifyProductAssets(path.join(dir,'output'),source,{sourcePath:rawPath});
        await durableFile(path.join(dir,'result.json'),{kind:'real-native-conversion',source,input:await hashFile(path.join(dir,'input.json')),tool:tool.evidence,files:verified.files,workspace:await workspaceBudget(this.root)});
        next = structuredClone(this.state); next.candidates.find((x) => x.productId === c.productId).preparation = {id:attemptId,result:await hashFile(path.join(dir,'result.json')),files:verified.files}; next.attempts.find((x) => x.id === attemptId).status = 'succeeded'; await this.commit(next,{type:'preparation-acknowledged',attemptId});
      } catch (e) {
        await durableFile(path.join(dir,'failure.json'),{message:e.message,at:new Date().toISOString()});
        next = structuredClone(this.state); Object.assign(next.attempts.find((x) => x.id === attemptId),{status:'failed',error:e.message,failure:await hashFile(path.join(dir,'failure.json'))}); await this.commit(next,{type:'preparation-failed',attemptId});
      }
    }
    return this.report();
  }
  async observe({productId,view,evidenceFile}) {
    assert(['front','side','back','material','orientation','dimensions'].includes(view));
    const c = this.state.candidates.find((c) => c.productId === productId); assert(c && !c.decision,'Candidate locked or unknown'); await this.verifyPreparation(c);
    assert(this.state.observations.filter((o)=>o.productId===productId).length<12,'At most twelve immutable view receipts per candidate; retain and use a new review workspace for more');
    const raw = await readFile(await externalFile(evidenceFile)); assert(raw.length > 20 && raw.length <= 20_000_000);
    assert(raw.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || raw.subarray(0,3).equals(Buffer.from([255,216,255])),'Evidence must be actual PNG/JPEG bytes');
    const budget=await workspaceBudget(this.root);assert(budget.bytes+raw.length<=MAX_WORKSPACE_BYTES,'View evidence would exceed the expansion workspace disk budget');
    const observationId = randomUUID(), file = `${observationId}.image`; await mkdir(await ownedPath(this.root,'evidence'),{recursive:true});
    const h = await open(await ownedPath(this.root,'evidence',file),'wx'); try { await h.writeFile(raw); await h.sync(); } finally { await h.close(); }
    const observation = {id:observationId,productId,view,file,pin:{bytes:raw.length,sha256:sha(raw)},preparationSha256:c.preparation.result.sha256,referencesSha256:this.state.freeze.references.sha256};
    const next = structuredClone(this.state); next.observations.push(observation); await this.commit(next,{type:'review-observation',observationId}); return observation;
  }
  validateDecision(productId,d) {
    if(d.decision === 'rejected' && Object.hasOwn(d,'technicalFailureAttemptId')) {
      keys(d,['productId','decision','technicalFailureAttemptId','reason']);assert.equal(d.productId,productId);text(d.reason);
      const attempt=this.state.attempts.find((a)=>a.id===d.technicalFailureAttemptId);
      assert(attempt?.productId===productId && attempt.status==='failed' && attempt.failure,'Technical rejection requires an acknowledged matching failed attempt');
      return;
    }
    keys(d,['productId','decision','notes','observationIds'],d.decision === 'accepted' ? ['category','rooms','privateStyleIds','placementClass','wallContactFaces','accessRegions'] : []);
    assert.equal(d.productId,productId); assert(['accepted','rejected'].includes(d.decision));
    keys(d.notes,['front','side','back','material','orientation','dimensions','suitability','style','access']); Object.values(d.notes).forEach(text);
    assert(Array.isArray(d.observationIds) && new Set(d.observationIds).size === d.observationIds.length);
    const c = this.state.candidates.find((c) => c.productId === productId), observations = d.observationIds.map((id) => this.state.observations.find((o) => o.id === id));
    assert(observations.every((o) => o?.productId === productId && o.preparationSha256 === c.preparation?.result.sha256),'Missing/current Mesh evidence required');
    assert(['front','side','back','material','orientation','dimensions'].every((v) => observations.some((o) => o.view === v)),'All six inspected views required');
    if (d.decision === 'accepted') { assert(c.preparation); functional(d); }
  }
  async review({decisionsFile,expectedRevision,operationId}) {
    assert(/^[a-zA-Z0-9-]{8,100}$/.test(operationId),'Stable operation ID required');
    const raw = await readFile(await externalFile(decisionsFile)); assert(raw.length <= 500_000);
    const document = JSON.parse(raw); keys(document,['schemaVersion','intakeSha256','reviewerIdentity','evidenceKind','decisions']);
    assert.equal(document.schemaVersion,1); assert.equal(document.intakeSha256,this.state.freeze.seedSha256); assert.equal(document.reviewerIdentity,this.state.freeze.reviewerIdentity); assert.equal(document.evidenceKind,this.state.evidenceKind);
    assert(document.decisions.length > 0 && document.decisions.length <= 50); assert.equal(new Set(document.decisions.map((d) => d.productId)).size,document.decisions.length);
    const old = this.state.operations.find((x) => x.operationId === operationId); if (old) { assert.equal(old.sha256,sha(raw)); return this.report(); }
    assert(Number.isInteger(expectedRevision) && expectedRevision === this.state.revision,'Stale review revision');
    for (const d of document.decisions) { this.source(d.productId); assert(!this.state.candidates.find((c) => c.productId === d.productId).decision,'Decision is immutable; retain and start a new review batch for revision'); this.validateDecision(d.productId,d); }
    const next = structuredClone(this.state); for (const d of document.decisions) next.candidates.find((c) => c.productId === d.productId).decision = d; next.operations.push({operationId,sha256:sha(raw)}); await this.commit(next,{type:'review-decisions',operationId,sha256:sha(raw)}); return this.report();
  }
  report() {
    const s = this.state; return {profile:s.freeze.profile,batchId:s.freeze.proposal.batchId,intakeSha256:s.freeze.seedSha256,reviewerIdentity:s.freeze.reviewerIdentity,evidenceKind:s.evidenceKind,ownerEvidenceStatus:'UNRUN',reviewEvidenceStatus:s.evidenceKind === 'genuine-agent-curation' && s.candidates.every((c) => c.decision) ? 'COMPLETED_VALID_AGENT_REVIEW' : 'UNRUN',revision:s.revision,counts:{candidates:s.candidates.length,prepared:s.candidates.filter((c) => c.preparation).length,accepted:s.candidates.filter((c) => c.decision?.decision === 'accepted').length,rejected:s.candidates.filter((c) => c.decision?.decision === 'rejected').length,failedAttempts:s.attempts.filter((a) => a.status === 'failed').length,interruptedAttempts:s.attempts.filter((a) => a.status === 'started').length},candidates:s.candidates,observations:s.observations,attempts:s.attempts};
  }
  async publication() {
    await this.verifyAcknowledged(); const report = this.report(); assert.equal(report.reviewEvidenceStatus,'COMPLETED_VALID_AGENT_REVIEW','Technical/unfinished review cannot promote');
    const entries = [];
    for (const c of this.state.candidates.filter((c) => c.decision.decision === 'accepted')) {
      const verified = await this.verifyPreparation(c), d = c.decision, p = this.source(c.productId);
      const record = Object.fromEntries(['productId','itemId','displayName','brand','colour','sourcePath','sourceSha256','sourceBytes'].map((k) => [k,p[k]]));
      Object.assign(record,Object.fromEntries(['category','placementClass','privateStyleIds','wallContactFaces','accessRegions'].map((k) => [k,d[k]])));
      entries.push({record,rooms:d.rooms,files:verified.files,reviewSha256:sha(canonical(d)),conversionSha256:c.preparation.result.sha256});
    }
    assert(entries.length,'No accepted Products'); const p = this.state.freeze.proposal;
    return {schemaVersion:1,profile:p.profile,batchId:p.batchId,intakeSha256:this.state.freeze.seedSha256,metadataSha256:p.metadataSha256,review:{actor:'agent',reviewerIdentity:p.reviewerIdentity,purpose:p.purpose,evidenceKind:p.evidenceKind,evidenceSha256:sha(canonical(report))},curatedOn:new Date(this.store.events[0].at).toISOString().slice(0,10),entries};
  }
  close() { return this.store.close(); }
}
export function preparationCandidates(candidates,productId) {
  if (!productId) return candidates;
  const candidate=candidates.find((c)=>c.productId===productId);
  assert(candidate && !candidate.decision,'Selected preparation candidate is unknown or has an immutable decision');
  return [candidate];
}
export function args(argv) {
  const [command,...rest] = argv, options = {};
  const names = {'--state-dir':'stateDir','--manifest':'manifest','--source-dir':'sourceDir','--product-id':'productId','--view':'view','--evidence-file':'evidenceFile','--decisions-file':'decisionsFile','--expected-revision':'expectedRevision','--operation-id':'operationId','--port':'port','--metadata-file':'metadataFile','--platform-bundle':'platformBundle','--bundle-sha256':'bundleSha256','--expected-project':'expectedProjectId','--expected-team':'expectedTeamId','--expected-plan':'expectedPlan','--delivery-method':'deliveryMethod','--proposed-runtime':'proposedRuntime'};
  for (let i = 0; i < rest.length; i++) { if (['--acquire','--apply'].includes(rest[i])) { const k = rest[i].slice(2); assert(!options[k]); options[k] = true; continue; } const key = names[rest[i]]; assert(key && rest[i+1] && options[key] === undefined,`Unknown/duplicate option ${rest[i]}`); options[key] = rest[++i]; }
  for (const k of ['expectedRevision','port']) if (options[k] !== undefined) { assert(/^\d+$/.test(options[k])); options[k] = Number(options[k]); }
  assert(options.stateDir && options.manifest,'Explicit external --state-dir and --manifest required'); return {command,options};
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const {command,options} = args(process.argv.slice(2)); const e = await Expansion.open(options);
  try {
    if (command === 'init' || command === 'report') console.log(JSON.stringify(e.report(),null,2));
    else if (command === 'prepare') { const report = await e.prepare(options); console.log(JSON.stringify(report,null,2)); const scope=options.productId?report.candidates.filter((c)=>c.productId===options.productId):report.candidates;if(scope.some((c)=>!c.preparation && c.decision?.decision!=='rejected'))process.exitCode=1; }
    else if (command === 'observe') console.log(JSON.stringify(await e.observe(options),null,2));
    else if (command === 'review') console.log(JSON.stringify(await e.review(options),null,2));
    else throw new Error('Use init | prepare | observe | review | report; server and promotion have separate entrypoints');
  } finally { await e.close(); }
}
