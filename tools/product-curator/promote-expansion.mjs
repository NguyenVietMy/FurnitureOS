import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, lstat, copyFile, open, rename } from 'node:fs/promises';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { BASE_RECORDS, BASE_CATALOGUE_VERSION } from '../../scripts/asset-pipeline.config.mjs';
import { batch, union, canonical, sha, loadExpansion, INDEX_POLICY, sourceRecord } from '../../scripts/lib/expansion-contract.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { noLinks, ownRoot, hashFile, ownedPath } from './safety.mjs';
import { durableFile } from './store.mjs';
import { adapter } from './catalogue.mjs';
import { Expansion, args } from './expansion.mjs';
import {promotionWriter} from './promotion-lock.mjs';

const exists = async (f) => { try { await lstat(f); return true; } catch(e) { if(e.code === 'ENOENT') return false; throw e; } };
async function exactCopy(source,target,pin) {
  await noLinks(target); await noLinks(source); await mkdir(path.dirname(target),{recursive:true});
  if (await exists(target)) assert.deepEqual(await hashFile(target),{bytes:pin.bytes,sha256:pin.sha256},`Conflicting bytes: ${target}`);
  else await copyFile(source,target,1);
  assert.deepEqual(await hashFile(target),{bytes:pin.bytes,sha256:pin.sha256});
  const h = await open(target,'r+'); try { await h.sync(); } finally { await h.close(); }
}

// Import-only test seam supports isolated external roots. Production CLI always targets REPO_ROOT.
// Fault hooks never change metadata meaning or relax validation.
async function installBatch({publication,directories,evidenceRoot,targetRoot=REPO_ROOT,baseRecords=BASE_RECORDS,baseVersion=BASE_CATALOGUE_VERSION,apply=false,onStep=async()=>{},deliveryOptions}) {
  batch(publication);
  // The exact production Pydantic metadata contract also validates before any write.
  assert.deepEqual(await adapter({mode:'expansion-batch',batch:publication}),publication);
  if (targetRoot !== REPO_ROOT) await ownRoot(targetRoot);
  await noLinks(targetRoot);
  const raw = canonical(publication), digest = sha(raw);
  const transaction = await ownedPath(evidenceRoot,'promotions',randomUUID()); await mkdir(transaction,{recursive:true});
  const meta = await noLinks(path.join(targetRoot,'api/catalogue/providers/expansion'));
  const current = loadExpansion(targetRoot,baseVersion,baseRecords);
  for(const r of baseRecords) await verifyProductAssets(await noLinks(path.join(targetRoot,'public/products',r.productId)),sourceRecord(r));
  const already = current.digests.includes(digest), conflicts = [];
  if (!already) {
    try { union(baseRecords,[...current.batches,publication]); } catch(e) { conflicts.push(e.message); }
  }
  for(const e of publication.entries) {
    const sourceDir = directories[e.record.productId]; assert(sourceDir);
    assert.deepEqual((await verifyProductAssets(await noLinks(sourceDir),sourceRecord(e.record))).files,e.files);
    const targetDir = await noLinks(path.join(targetRoot,'public/products',e.record.productId));
    if(await exists(targetDir)) {
      const {readdir}=await import('node:fs/promises');
      for(const item of await readdir(targetDir,{recursive:true,withFileTypes:true})) {
        const relative=path.relative(targetDir,path.join(item.parentPath,item.name)).replaceAll('\\','/');
        if(item.isSymbolicLink() || item.isFile() && !e.files.some((f)=>f.file===relative) || item.isDirectory() && relative!=='textures') conflicts.push(`${targetDir}: unexpected ${relative}`);
      }
    }
    for(const f of e.files) if(await exists(path.join(targetDir,f.file))) {
      try { assert.deepEqual(await hashFile(await noLinks(path.join(targetDir,f.file))),{bytes:f.bytes,sha256:f.sha256}); } catch { conflicts.push(path.join(targetDir,f.file)); }
    }
  }
  await durableFile(path.join(transaction,'dry-run.json'),{digest,publication,conflicts,apply,already,baseVersion,indexBefore:current.digests});
  if(!apply) return {transaction,digest,conflicts,already};
  assert.equal(conflicts.length,0,'Promotion conflicts; see retained dry run');
  const prospectiveFiles = [...baseRecords.map((r) => {
    // Existing manifests declare the complete asset union; independent asset
    // validation below proves the on-disk publication before activation.
    const d = path.join(targetRoot,'public/products',r.productId);
    return d;
  })];
  let productBytes=0,productFiles=0;
  const { readdir } = await import('node:fs/promises');
  const visit = async (d) => { for(const f of await readdir(await noLinks(d),{withFileTypes:true})) { const p = await noLinks(path.join(d,f.name)); if(f.isDirectory()) await visit(p); else {productBytes += (await lstat(p)).size; productFiles++;} } };
  for(const d of prospectiveFiles) await visit(d);
  for(const b of [...current.batches,...(already ? [] : [publication])]) for(const e of b.entries) {productBytes += e.files.reduce((n,f)=>n+f.bytes,0); productFiles += e.files.length;}
  assert(productBytes <= 1_500_000_000 && productFiles <= 25_000,'Aggregate Product task ceiling exceeded');
  if(targetRoot === REPO_ROOT) {
    assert(deliveryOptions?.platformBundle && deliveryOptions.bundleSha256 && deliveryOptions.expectedTarget,'Local source promotion requires the pinned receipt bundle and explicit expected target; this grants no publication authority');
    const {deliveryReport} = await import('../../scripts/report-delivery.mjs');
    const {assessDelivery}=await import('../../scripts/lib/platform-evidence.mjs');
    const report = deliveryReport(deliveryOptions); await durableFile(path.join(transaction,'delivery-before.json'),report);
    assert(!report.failures.length && report.platform && report.distPresent,'Delivery evidence/task ceilings are not ready');
    const added = already ? 0 : publication.entries.flatMap((e)=>e.files).reduce((n,f)=>n+f.bytes,0);
    const indexAndBatchBytes=already ? 0 : Buffer.byteLength(raw)+8192;
    const metadataBytes = already ? 0 : indexAndBatchBytes+publication.entries.reduce((n,e)=>n+e.files.find((f)=>f.file === 'asset-manifest.json').bytes,0);
    // Reserve both the new batch and index paths, including a first activation.
    // An already present index makes this count conservatively one file high.
    const prospective=assessDelivery({metrics:{productBytes,productFiles,distBytes:report.metrics.distBytes+added,manifestBytes:report.metrics.manifestBytes+metadataBytes,functionBytes:report.metrics.functionBytes+metadataBytes},sourceUpload:{...report.sourceUpload,uncompressedBytes:report.sourceUpload.uncompressedBytes+added+indexAndBatchBytes,files:report.sourceUpload.files+(already?0:publication.entries.reduce((n,e)=>n+e.files.length,0)+2)},staticFiles:report.staticFiles+(already?0:publication.entries.reduce((n,e)=>n+e.files.length,0)),buildDiskEstimateBytes:report.buildDiskEstimateBytes+2*added+metadataBytes,evidence:report.platform});
    await durableFile(path.join(transaction,'delivery-prospective.json'),{...prospective,scope:'Conservative prospective source/data activation only; actual Git connection/build/deployment and public readiness UNRUN'});
    assert.equal(prospective.failures.length,0,'Prospective source/data exceeds applicable CLI or task/documented limits');
  }
  await mkdir(meta,{recursive:true}); const release = await promotionWriter(meta,transaction);
  try {
    const latest = loadExpansion(targetRoot,baseVersion,baseRecords);
    assert.deepEqual(latest.digests,current.digests,'Index changed after inventory; rerun dry-run');
    if(already) { await durableFile(path.join(transaction,'applied.json'),{digest,idempotent:true,index:latest.digests}); return {transaction,digest,already:true}; }
    union(baseRecords,[...latest.batches,publication]);
    for(const e of publication.entries) {
      const staged = await ownedPath(evidenceRoot,'promotions',path.basename(transaction),e.record.productId); await mkdir(staged,{recursive:true});
      for(const f of e.files) await exactCopy(path.join(directories[e.record.productId],f.file),path.join(staged,f.file),f);
      assert.deepEqual((await verifyProductAssets(staged,sourceRecord(e.record))).files,e.files);
    }
    await onStep('staged');
    for(const e of publication.entries) {
      const target = await noLinks(path.join(targetRoot,'public/products',e.record.productId));
      for(const f of e.files) { await exactCopy(path.join(transaction,e.record.productId,f.file),path.join(target,f.file),f); await onStep('file'); }
      assert.deepEqual((await verifyProductAssets(target,sourceRecord(e.record))).files,e.files,'Installed complete union differs');
    }
    const manifest = path.join(meta,`${digest}.json`);
    const stagedManifest = path.join(transaction,'batch.json'); await durableFile(stagedManifest,publication);
    // Batch files are canonical raw bytes, independent of evidence JSON formatting.
    const rawFile = path.join(transaction,'batch.canonical.json'), h = await open(rawFile,'wx'); try { await h.writeFile(raw); await h.sync(); } finally { await h.close(); }
    await exactCopy(rawFile,manifest,{bytes:Buffer.byteLength(raw),sha256:digest});
    await onStep('batch');
    const index = {schemaVersion:1,policyVersion:INDEX_POLICY,baseVersion,batches:[...latest.digests,digest]};
    // Old union was re-opened above under the serialization lock; reopen again
    // immediately before activation to catch drift while new files were copied.
    loadExpansion(targetRoot,baseVersion,baseRecords);
    assert.equal(sha(await readFile(await noLinks(manifest))),digest);
    for(const e of publication.entries) assert.deepEqual((await verifyProductAssets(path.join(targetRoot,'public/products',e.record.productId),sourceRecord(e.record))).files,e.files);
    const pending = path.join(meta,`.index-${randomUUID()}.pending`); await durableFile(pending,index);
    await onStep('before-index'); release.assertHeld(); await rename(pending,path.join(meta,'index.json')); await onStep('after-index');
    const activated = loadExpansion(targetRoot,baseVersion,baseRecords); assert.deepEqual(activated.digests,index.batches);
    await durableFile(path.join(transaction,'applied.json'),{digest,index:await hashFile(path.join(meta,'index.json')),catalogueVersion:activated.version});
    return {transaction,digest,catalogueVersion:activated.version,already:false};
  } finally { await release(); }
}
export async function promoteExpansion(options) {
  const e = await Expansion.open(options);
  try {
    const publication = await e.publication(), directories = {};
    for(const c of e.state.candidates.filter((c) => c.decision?.decision === 'accepted')) directories[c.productId] = (await e.verifyPreparation(c)).directory;
    return await installBatch({publication,directories,evidenceRoot:e.root,apply:options.apply,deliveryOptions:{platformBundle:options.platformBundle,bundleSha256:options.bundleSha256,proposedRuntime:options.proposedRuntime,expectedTarget:{projectId:options.expectedProjectId,teamId:options.expectedTeamId,plan:options.expectedPlan,deliveryMethod:options.deliveryMethod}}});
  } finally { await e.close(); }
}
export async function installFixtureBatch(options) {
  assert(options.targetRoot && path.resolve(options.targetRoot) !== REPO_ROOT,'Fixture promotion requires an isolated external root');
  await ownRoot(options.targetRoot);
  return installBatch(options);
}
if(process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const {command,options} = args(process.argv.slice(2)); assert.equal(command,'promote'); console.log(JSON.stringify(await promoteExpansion(options),null,2));
}
