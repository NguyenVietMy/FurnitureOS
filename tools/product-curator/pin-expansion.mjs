// Bounded source acquisition AFTER coordinator review of the metadata selection.
// This creates pins and source bytes only, never Style/access/acceptance decisions.
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFile, mkdir, open } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { intake, sha } from '../../scripts/lib/expansion-contract.mjs';
import { ownRoot, ownedPath, assertLocalContext, hashFile } from './safety.mjs';
import { externalFile } from './expansion.mjs';
import { durableFile } from './store.mjs';
import {selfContainedGlb} from '../../scripts/lib/source-glb.mjs';

assertLocalContext();
const argv=process.argv.slice(2), options={};
for(let i=0;i<argv.length;i+=2) { assert(['--selection','--selection-review','--metadata-file','--state-dir'].includes(argv[i]) && argv[i+1] && !options[argv[i]]); options[argv[i]]=argv[i+1]; }
assert(Object.keys(options).length===4,'Use --selection <coordinator-selected.json> --selection-review <actual-coordinator-receipt> --metadata-file <abo-listings.json> --state-dir <new-external-pin-root>');
const root=await ownRoot(options['--state-dir']), selectionRaw=await readFile(await externalFile(options['--selection']));
assert(selectionRaw.length<=200_000); const selected=JSON.parse(selectionRaw);
for(const c of selected.candidates) { assert(!Object.hasOwn(c,'sourceSha256') && !Object.hasOwn(c,'sourceBytes'),'Selection is unpinned; use prepare for an already pinned intake'); }
intake({...selected,candidates:selected.candidates.map((c)=>({...c,sourceSha256:sha(c.modelId),sourceBytes:1}))});
const metadata=await readFile(await externalFile(options['--metadata-file'])); assert.equal(sha(metadata),selected.metadataSha256);
const pairs=new Set(metadata.toString('utf8').split(/\r?\n/).filter((l)=>l.trim()).map((l)=>{const r=JSON.parse(l);return `${r.item_id}/${r['3dmodel_id']}`;}));
assert(selected.candidates.every((c)=>pairs.has(`${c.itemId}/${c.modelId}`)),'Selection item/model pair absent from official metadata');
const review=await readFile(await externalFile(options['--selection-review'])); assert(review.length>20 && review.length<=100_000,'Actual coordinator selection-review receipt required');
await durableFile(await ownedPath(root,'acquisition-input.json'),{selectionSha256:sha(selectionRaw),metadataSha256:sha(metadata),selectionReview:{bytes:review.length,sha256:sha(review)},purpose:'Bounded source pinning only; no accepted Products',selection:selected});
await mkdir(await ownedPath(root,'sources'));
const candidates=[];let total=0;
for(const c of selected.candidates) {
  const attempt=await ownedPath(root,'attempts',randomUUID());await mkdir(attempt,{recursive:true});
  await durableFile(path.join(attempt,'input.json'),c);
  try {
    const response=await fetch(c.sourceUrl,{redirect:'error',signal:AbortSignal.timeout(120_000)});assert(response.ok,`HTTP ${response.status}`);
    if(response.headers.has('content-length')) assert(Number(response.headers.get('content-length'))<=100_000_000);
    const file=path.join(attempt,`${c.modelId}.glb`),h=await open(file,'wx'); let size=0;
    try {for await(const chunk of response.body) {size+=chunk.length;total+=chunk.length;assert(size<=100_000_000 && total<=1_000_000_000,'Bounded acquisition disk limit');await h.write(chunk);}await h.sync();}finally{await h.close();}
    await selfContainedGlb(file);
    const pin=await hashFile(file), record={...c,sourceSha256:pin.sha256,sourceBytes:pin.bytes};
    const {copyFile}=await import('node:fs/promises');await copyFile(file,await ownedPath(root,'sources',`${c.modelId}.glb`),1);
    await durableFile(path.join(attempt,'result.json'),{candidate:record,pin});candidates.push(record);
  } catch(e) {await durableFile(path.join(attempt,'failure.json'),{message:e.message});throw e;}
}
const manifest=intake({...selected,candidates});await durableFile(await ownedPath(root,'intake-pinned.json'),manifest);
console.log(JSON.stringify({manifest:path.join(root,'intake-pinned.json'),sourceDir:path.join(root,'sources'),candidates:candidates.length,sourceBytes:total,acceptedProducts:0,evidenceKind:'source-acquisition-only'},null,2));
