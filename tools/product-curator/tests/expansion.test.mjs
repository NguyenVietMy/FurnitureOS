import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFile, writeFile, mkdir, cp, rename, readdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { REPO_ROOT } from '../../../scripts/lib/paths.mjs';
import { intake, functional, canonical, sha, batch, loadExpansion, union, METADATA_SHA256, PROFILE, sourceRecord } from '../../../scripts/lib/expansion-contract.mjs';
import { verifyProductAssets } from '../../../scripts/lib/verify-product-assets.mjs';
import { Expansion,preparationCandidates } from '../expansion.mjs';
import { installFixtureBatch } from '../promote-expansion.mjs';
import { evidenceDir } from './helpers.mjs';
import { ownRoot } from '../safety.mjs';
import {selfContainedGlb} from '../../../scripts/lib/source-glb.mjs';
import {durableFile} from '../store.mjs';
import {hashFile} from '../safety.mjs';
import {spawnSync} from 'node:child_process';
import {promotionWriter} from '../promotion-lock.mjs';

const seed = JSON.parse(await readFile(path.join(REPO_ROOT,'api/catalogue/providers/abo-seed.json')));
const r = seed.products.find((p)=>p.category === 'nightstand');
const candidate = {productId:r.productId,itemId:r.itemId,modelId:r.itemId,displayName:r.displayName,brand:r.brand,colour:r.colour,proposedCategory:r.category,sourcePath:r.sourcePath,sourceUrl:sourceRecord(r).sourceUrl,sourceSha256:r.sourceSha256,sourceBytes:r.sourceBytes};
const proposal = () => ({schemaVersion:1,profile:PROFILE,batchId:'automated-contract-fixture',actor:'agent',reviewerIdentity:'automated-test-NOT-genuine-review',purpose:'Automated isolated contract test; no Product acceptance evidence',metadataSha256:METADATA_SHA256,evidenceKind:'technical-only',candidates:[structuredClone(candidate)]});
test('selected preparation retry cannot rerun unrelated failures or touch immutable reviewer decisions',()=>{
  const entries=[{productId:'pending-bounds',preparation:null,decision:null},{productId:'over-budget',preparation:null,decision:null},{productId:'already-accepted',preparation:{id:'existing'},decision:{decision:'accepted'}}];
  assert.deepEqual(preparationCandidates(entries,'pending-bounds'),[entries[0]]);
  assert.throws(()=>preparationCandidates(entries,'unknown'),/unknown/);
  assert.throws(()=>preparationCandidates(entries,'already-accepted'),/immutable/);
  assert.equal(entries[1].preparation,null);assert.equal(entries[2].decision.decision,'accepted');
});
async function fixture() {
  const base = await evidenceDir('expansion'), state = path.join(base,'state'), targetRoot = path.join(base,'destination'); await ownRoot(state); await ownRoot(targetRoot);
  const verified = await verifyProductAssets(path.join(REPO_ROOT,'public/products',r.productId),sourceRecord(r));
  const record = {...r,placementClass:'floor-standing',accessRegions:[{face:'front',depthM:0.6,required:true,purpose:'Controlled contract fixture access'}]}; delete record.listingDimensions;
  // This synthetic metadata only exercises the installer in an owned external
  // destination. It is never review evidence or a production acceptance row.
  const publication = {schemaVersion:1,profile:PROFILE,batchId:'automated-isolated-fixture',intakeSha256:'0'.repeat(64),metadataSha256:METADATA_SHA256,review:{actor:'agent',reviewerIdentity:'automated-fixture-NOT-review',purpose:'Isolated installer contract test only',evidenceKind:'genuine-agent-curation',evidenceSha256:'0'.repeat(64)},curatedOn:'2026-10-29',entries:[{record,rooms:['bedroom'],files:verified.files,reviewSha256:'0'.repeat(64),conversionSha256:'0'.repeat(64)}]};
  const options = {publication,directories:{[r.productId]:path.join(REPO_ROOT,'public/products',r.productId)},evidenceRoot:state,targetRoot,baseRecords:[],baseVersion:'isolated-fixture-base',apply:true};
  return {base,state,targetRoot,publication,options};
}
test('expansion intake is separate, bounded, pinned and rejects source/identity/tag mistakes',()=>{
  intake(proposal());
  const coffee=proposal();coffee.candidates[0].proposedCategory='coffee-table';intake(coffee);
  assert.throws(()=>functional({category:'coffee-table',rooms:['living-room'],privateStyleIds:['style-01']}),'A proposed role cannot become an accepted Product category automatically');
  for(const change of [p=>p.candidates.push(p.candidates[0]),p=>p.profile='living-seed-v1',p=>p.candidates[0].sourcePath='../escape.glb',p=>p.candidates[0].sourceUrl='https://evil.example/a.glb',p=>p.candidates[0].sourceBytes=100_000_001,p=>p.metadataSha256='0'.repeat(64),p=>p.candidates[0].privateStyleIds=['style-01'],p=>p.candidates=Array(51).fill(p.candidates[0])]) {const p=proposal(); change(p); assert.throws(()=>intake(p));}
});
test('functional review requires category-specific access and rejects unsafe roles',()=>{
  const d={category:'bed',rooms:['bedroom'],privateStyleIds:['style-01'],placementClass:'floor-standing',wallContactFaces:['back'],accessRegions:['left','right','front'].map((face)=>({face,depthM:0.6,required:true,purpose:'getting in/out and circulation'}))}; functional(d);
  for(const change of [x=>x.placementClass='floor-covering',x=>x.accessRegions.pop(),x=>x.accessRegions[0].depthM=0.2,x=>x.wallContactFaces.push('left'),x=>x.rooms=['living-room'],x=>x.privateStyleIds=['style-99']]) {const x=structuredClone(d);change(x);assert.throws(()=>functional(x));}
});
test('source originals cannot load external filesystem or network resources',async()=>{
  const root=await evidenceDir('glb-source');
  function glb(document) {const json=Buffer.from(JSON.stringify(document));const size=Math.ceil(json.length/4)*4;const raw=Buffer.alloc(20+size+12,32);raw.write('glTF');raw.writeUInt32LE(2,4);raw.writeUInt32LE(raw.length,8);raw.writeUInt32LE(size,12);raw.writeUInt32LE(0x4e4f534a,16);json.copy(raw,20);raw.writeUInt32LE(4,20+size);raw.writeUInt32LE(0x004e4942,24+size);return raw;}
  const valid={asset:{version:'2.0'},buffers:[{byteLength:4}],bufferViews:[{buffer:0,byteOffset:0,byteLength:4}],images:[{bufferView:0,mimeType:'image/png'}]};
  const file=path.join(root,'source.glb');await writeFile(file,glb(valid));await selfContainedGlb(file);
  for(const change of [d=>d.buffers[0].uri='../../escape.bin',d=>d.images[0].uri='https://example.invalid/image.png',d=>d.buffers.push({uri:'file:///private'}),d=>d.bufferViews[0].buffer=2]) {const d=structuredClone(valid);change(d);await writeFile(file,glb(d));await assert.rejects(selfContainedGlb(file));}
});
test('journal resume binds actor/evidence/source; missing marker and corruption fail closed',async()=>{
  const base=await evidenceDir('expansion-journal'),manifest=path.join(base,'intake.json'),stateDir=path.join(base,'review'); await writeFile(manifest,JSON.stringify(proposal()));
  let e=await Expansion.open({stateDir,manifest}); assert.equal(e.report().counts.accepted,0); await assert.rejects(e.publication(),/Technical\/unfinished/); await e.close();
  e=await Expansion.open({stateDir,manifest}); await e.close();
  const changedReviewer=proposal();changedReviewer.reviewerIdentity='different-actor';await writeFile(manifest,JSON.stringify(changedReviewer));await assert.rejects(Expansion.open({stateDir,manifest}),/identity|seed/i);
  const p=proposal();p.evidenceKind='genuine-agent-curation';await writeFile(manifest,JSON.stringify(p)); await assert.rejects(Expansion.open({stateDir,manifest}),/identity|seed|metadata/i);
  await writeFile(manifest,JSON.stringify(proposal())); await rename(path.join(stateDir,'journal-initialized.json'),path.join(stateDir,'retained-marker.json')); await assert.rejects(Expansion.open({stateDir,manifest}),/Missing initialization marker/);
});
test('unacknowledged output directories never become prepared or accepted on resume',async()=>{
  const base=await evidenceDir('expansion-orphan'),manifest=path.join(base,'intake.json'),stateDir=path.join(base,'review'); await writeFile(manifest,JSON.stringify(proposal()));
  const e=await Expansion.open({stateDir,manifest}); await mkdir(path.join(stateDir,'attempts',randomUUID(),'output'),{recursive:true}); await e.close();
  const resumed=await Expansion.open({stateDir,manifest}); try {assert.equal(resumed.report().counts.prepared,0);await assert.rejects(resumed.review({decisionsFile:manifest,expectedRevision:0,operationId:'bad-test-operation'}));}finally{await resumed.close();}
});
test('technical rejection cites a real failure receipt; retries are idempotent and cannot become acceptance',async()=>{
  const root=await evidenceDir('technical-rejection'),stateDir=path.join(root,'state'),manifest=path.join(root,'intake.json');await writeFile(manifest,JSON.stringify(proposal()));
  let e=await Expansion.open({stateDir,manifest});
  const attemptId=randomUUID(),dir=path.join(stateDir,'attempts',attemptId);await mkdir(dir,{recursive:true});await durableFile(path.join(dir,'failure.json'),{kind:'CONTROLLED-technical-test',message:'Synthetic failure fixture, no native attempt or visual review'});
  const next=structuredClone(e.state);next.attempts.push({id:attemptId,productId:r.productId,status:'failed',failure:await hashFile(path.join(dir,'failure.json'))});await e.commit(next,{type:'CONTROLLED-failure-fixture'});
  const decisionsFile=path.join(root,'decisions.json');const decision={productId:r.productId,decision:'rejected',technicalFailureAttemptId:attemptId,reason:'Controlled technical rejection test, no visual suitability judgment'};
  assert.throws(()=>e.validateDecision(r.productId,{...decision,technicalFailureAttemptId:'unknown'}));
  await writeFile(decisionsFile,JSON.stringify({schemaVersion:1,intakeSha256:e.state.freeze.seedSha256,reviewerIdentity:e.state.freeze.reviewerIdentity,evidenceKind:'technical-only',decisions:[decision]}));
  const options={decisionsFile,expectedRevision:e.state.revision,operationId:'stable-technical-rejection'};
  const report=await e.review(options);assert.equal(report.counts.rejected,1);assert.equal(report.counts.accepted,0);assert.equal(report.reviewEvidenceStatus,'UNRUN');
  assert.deepEqual(await e.review(options),report);await assert.rejects(e.publication(),/Technical\/unfinished/);await e.close();
  e=await Expansion.open({stateDir,manifest});await e.close();await writeFile(path.join(dir,'failure.json'),'changed');await assert.rejects(Expansion.open({stateDir,manifest}),/failure receipt drift/);
});
for(const step of ['staged','file','batch','before-index','after-index']) test(`promotion interruption at ${step} advertises a complete old or new union and resumes`,async()=>{
  const f=await fixture(); let fired=false;
  await assert.rejects(installFixtureBatch({...f.options,onStep:async(s)=>{if(s===step&&!fired){fired=true;throw new Error('SIMULATED-INTERRUPTION');}}}),/SIMULATED-INTERRUPTION/);
  const before=loadExpansion(f.targetRoot,f.options.baseVersion,[]); assert.equal(before.entries.length,step==='after-index'?1:0);
  await installFixtureBatch(f.options); const after=loadExpansion(f.targetRoot,f.options.baseVersion,[]);assert.equal(after.entries.length,1);
  const repeat=await installFixtureBatch(f.options); assert.equal(repeat.already,true);assert.equal(loadExpansion(f.targetRoot,f.options.baseVersion,[]).version,after.version);
});
test('global duplicates, changed files and corrupt/missing manifests fail closed without overwrite',async()=>{
  const f=await fixture();await installFixtureBatch(f.options);
  const second=structuredClone(f.publication);second.batchId='different-batch';assert.throws(()=>union([], [f.publication,second]),/duplicate/i);
  const dry=await installFixtureBatch({...f.options,publication:second,apply:false}); assert(dry.conflicts.length);
  const file=path.join(f.targetRoot,'public/products',r.productId,'lod0.bin'),original=await readFile(file);await writeFile(file,'corrupt');assert.throws(()=>loadExpansion(f.targetRoot,f.options.baseVersion,[]));await assert.rejects(installFixtureBatch(f.options));assert.equal((await readFile(file)).toString(),'corrupt');await writeFile(file,original);
  const digest=sha(canonical(f.publication));await rename(path.join(f.targetRoot,'api/catalogue/providers/expansion',`${digest}.json`),path.join(f.base,'retained-batch.json'));assert.throws(()=>loadExpansion(f.targetRoot,f.options.baseVersion,[]));
});
test('dry run inventories extra orphan files before any publication write',async()=>{
  const f=await fixture(),dir=path.join(f.targetRoot,'public/products',r.productId);await mkdir(dir,{recursive:true});await writeFile(path.join(dir,'retained-unexpected.txt'),'CONTROLLED orphan conflict');
  const dry=await installFixtureBatch({...f.options,apply:false});assert(dry.conflicts.some((c)=>c.includes('retained-unexpected.txt')));
  await assert.rejects(installFixtureBatch(f.options),/Promotion conflicts/);assert.equal((await readFile(path.join(dir,'retained-unexpected.txt'))).toString(),'CONTROLLED orphan conflict');
  assert.equal(loadExpansion(f.targetRoot,f.options.baseVersion,[]).entries.length,0);
});
test('concurrent promotions serialize and preserve active index',async()=>{
  const f=await fixture();let release,entered;const ready=new Promise(r=>entered=r),wait=new Promise(r=>release=r);
  const first=installFixtureBatch({...f.options,onStep:async(s)=>{if(s==='staged'){entered();await wait;}}});await ready;
  try {await assert.rejects(installFixtureBatch(f.options),/Concurrent promotion/);}finally{release();}await first;
  assert.equal(loadExpansion(f.targetRoot,f.options.baseVersion,[]).entries.length,1);
});
test('promotion process transients stay out of source inventory and abandoned pending bytes survive external recovery',async()=>{
  const pendingName=`.index-${randomUUID()}.pending`,prefix='api/catalogue/providers/expansion/';
  const paths=[prefix+'.promotion.lock',prefix+pendingName,prefix+'index.json',prefix+'a'.repeat(64)+'.json',prefix+'.index-arbitrary-source.pending'];
  const ignored=spawnSync('git',['check-ignore','--no-index','-z','--stdin'],{cwd:REPO_ROOT,input:paths.join('\0')+'\0',encoding:'utf8'});assert([0,1].includes(ignored.status));assert.deepEqual(ignored.stdout.split('\0').filter(Boolean),paths.slice(0,2));
  const f=await fixture();let captured;
  await assert.rejects(installFixtureBatch({...f.options,onStep:async(step)=>{if(step==='before-index'){const meta=path.join(f.targetRoot,'api/catalogue/providers/expansion');const name=(await readdir(meta)).find(n=>n.endsWith('.pending'));captured=await readFile(path.join(meta,name));throw new Error('CONTROLLED pending-index interruption');}}}),/pending-index interruption/);
  await installFixtureBatch(f.options);
  const meta=path.join(f.targetRoot,'api/catalogue/providers/expansion');assert(!(await readdir(meta)).some(n=>n.endsWith('.pending') || n.startsWith('stale-lock-')));
  assert.equal((await readFile(path.join(meta,'.promotion.lock'))).toString(),' ');
  const evidence=await readdir(f.options.evidenceRoot,{recursive:true});const retained=evidence.filter(n=>n.includes('recovered-transients') && n.endsWith('.pending'));
  assert(retained.length>0);assert((await Promise.all(retained.map(n=>readFile(path.join(f.options.evidenceRoot,n))))).some(b=>b.equals(captured)));
});
test('OS promotion lock refuses live legacy PID, retains proven-dead bytes and releases after helper death',async()=>{
  const root=await evidenceDir('promotion-OS-lock'),meta=path.join(root,'metadata');await mkdir(meta);
  const lock=path.join(meta,'.promotion.lock'),live=Buffer.from(JSON.stringify({id:randomUUID(),pid:process.pid}));await writeFile(lock,live);
  const first=path.join(root,'live-refusal');await mkdir(first);await assert.rejects(promotionWriter(meta,first),/Concurrent promotion legacy/);assert((await readFile(lock)).equals(live));
  const ended=spawnSync(process.execPath,['-e','process.exit(0)']);assert.equal(ended.status,0);assert.throws(()=>process.kill(ended.pid,0),e=>e.code==='ESRCH');
  const dead=Buffer.from(JSON.stringify({id:randomUUID(),pid:ended.pid}));await writeFile(lock,dead);
  const second=path.join(root,'dead-recovery');await mkdir(second);const release=await promotionWriter(meta,second);
  const receipt=JSON.parse(await readFile(path.join(second,'lock-acquired.json')));assert((await readFile(receipt.legacy.file)).equals(dead));release.assertHeld();
  process.kill(receipt.helperPid);await assert.rejects(release(),/Promotion lock helper exit/);assert.throws(()=>release.assertHeld(),/lease ended/);
  const third=path.join(root,'after-death');await mkdir(third);const next=await promotionWriter(meta,third);next.assertHeld();await next();assert.equal((await readFile(lock)).toString(),' ');
});
