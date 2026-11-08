// Read-only defensive ceilings. Platform readiness needs coordinator-verified caps.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, lstatSync, existsSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PUBLISHED_CATALOGUE_VERSION, PUBLISHED_PRODUCT_ASSET_SOURCES } from './asset-pipeline.config.mjs';
import { sha, pin, noLinkedPath } from './lib/expansion-contract.mjs';
import {TASK_CEILINGS,verifyPlatformBundle,verifyHostedReceipt,assessDelivery} from './lib/platform-evidence.mjs';
import {verifyFunctionBundle} from './lib/function-bundle.mjs';

const root = fileURLToPath(new URL('../',import.meta.url));
export const CEILINGS = TASK_CEILINGS;
function files(dir,{dependencyEstimate=false}={}) {
  if(!existsSync(dir)) return [];
  return readdirSync(dir,{withFileTypes:true}).flatMap((e)=>{const f = path.join(dir,e.name); if(lstatSync(f).isSymbolicLink()) {assert(dependencyEstimate,'Linked delivery input');return [];} return e.isDirectory() ? files(f,{dependencyEstimate}) : [f];});
}
const sum = (fs) => fs.reduce((n,f)=>n+lstatSync(f).size,0);
export function deliveryReport({platformBundle,bundleSha256,expectedTarget,proposedRuntime,hostedReceipt,hostedReceiptSha256,expectedSource,sourceProjection,sourceProjectionSha256,functionBundle,functionBundleSha256,platformLimits}={}) {
  assert(!platformLimits,'Assertion-only platform-limits files are retired; use a hash-pinned receipt bundle and explicit expected target');
  const productFiles = PUBLISHED_PRODUCT_ASSET_SOURCES.flatMap((s)=>files(path.join(root,'public/products',s.productId)));
  const manifests = files(path.join(root,'api/catalogue/providers')).filter((f)=>f.endsWith('.json'));
  const functionFiles = [...files(path.join(root,'api')), ...files(path.join(root,'public/style-references'))].filter((f)=> !f.includes('__pycache__') && !f.endsWith('.pyc'));
  // This selective runtime inventory misses reachable build output (e.g. dist).
  // Keep it only as a labelled estimate; never use it to pass a function cap.
  const dependencyFiles = files(path.join(root,'.venv/Lib/site-packages')).filter((f)=>!f.includes('__pycache__') && !f.endsWith('.pyc'));
  const inventory=(args)=>execFileSync('git',args,{cwd:root}).toString().split('\0').filter(Boolean);
  const sourcePaths = [...new Set([...inventory(['ls-files','--cached','--others','--exclude-standard','-z']),...inventory(['ls-tree','-r','--name-only','-z','HEAD'])])].sort();
  const deletedPaths=sourcePaths.filter((f)=>!existsSync(path.join(root,f)));
  const sourceFiles = sourcePaths.filter((f)=>!deletedPaths.includes(f)).map((f)=>noLinkedPath(path.join(root,f)));
  assert(Boolean(functionBundle)===Boolean(functionBundleSha256),'Function bundle path and pin required together');
  const functionPackage=functionBundle?verifyFunctionBundle({bundlePath:functionBundle,bundleSha256:functionBundleSha256,root}):null;
  // Hash-valid local inventories cannot establish a complete actual invocation.
  const metrics = {productBytes:sum(productFiles),productFiles:productFiles.length,distBytes:sum(files(path.join(root,'dist'))),manifestBytes:sum(manifests),functionBytes:null};
  const sourceUpload = {method:'Complete nonignored source inventory including tool/docs/test source; excludes ignored dependencies/build outputs. Gzip per file excludes archive/HTTP overhead. Estimate, not a deployment receipt.',uncompressedBytes:sum(sourceFiles),compressedBytes:sourceFiles.reduce((n,f)=>n+gzipSync(readFileSync(f)).length,0),files:sourceFiles.length};
  let projection=null;
  if(sourceProjection) {
    const raw=readFileSync(noLinkedPath(sourceProjection));assert.equal(sha(raw),pin(sourceProjectionSha256));const p=JSON.parse(raw);
    assert.equal(p.schemaVersion,'furnitureos-source-projection-v1');assert.deepEqual(p.records.map((r)=>r.path).sort(),sourcePaths);
    const python=path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
    execFileSync(python,['scripts/source_projection.py','verify-raw','--projection',path.resolve(sourceProjection),'--projection-sha256',sourceProjectionSha256],{cwd:root,stdio:'pipe'});
    for(const r of p.records) {
      if(r.status==='deleted') {assert(deletedPaths.includes(r.path));continue;}
      const b=readFileSync(noLinkedPath(path.join(root,r.path)));assert.equal(b.length,r.raw.bytes);assert.equal(sha(b),r.raw.sha256);
    }
    projection={sha256:sourceProjectionSha256,deploymentBytes:p.records.reduce((n,r)=>n+(r.deployment?.bytes??0),0),deploymentFiles:p.records.filter((r)=>r.status!=='deleted').length,rawWorkingBytes:sourceUpload.uncompressedBytes,expectedCommit:'UNRUN_AUTHORIZATION_REQUIRED'};
  }
  const evidence=platformBundle?verifyPlatformBundle({bundlePath:platformBundle,bundleSha256,expectedTarget,proposedRuntime}):null;
  assert(!hostedReceipt || evidence,'Hosted receipt requires a verified target evidence bundle');
  const hosted=hostedReceipt?verifyHostedReceipt({receiptPath:hostedReceipt,receiptSha256:hostedReceiptSha256,expectedTarget,expectedSource}):null;
  const staticFiles = files(path.join(root,'dist')).length;
  const buildDiskEstimateBytes=sourceUpload.uncompressedBytes+metrics.distBytes+(functionPackage?.inventory.bytes??(sum(functionFiles)+sum(dependencyFiles)))+sum(files(path.join(root,'node_modules'),{dependencyEstimate:true}));
  const assessment=assessDelivery({metrics,sourceUpload,staticFiles,buildDiskEstimateBytes,evidence,hostedReceipt:hosted});
  return {schemaVersion:4,catalogueVersion:PUBLISHED_CATALOGUE_VERSION,uniqueProducts:PUBLISHED_PRODUCT_ASSET_SOURCES.length,metrics,staticFiles,sourceUpload:{...sourceUpload,byteView:'RAW_WORKING_TREE',intendedDeletions:deletedPaths},projection,buildDiskEstimateBytes,buildDiskEstimateScope:'Raw source + local dist + diagnostic file inventory or selective runtime estimate + installed Node regular files; runtime closure and actual hosted allocation UNRUN',functionPackage,functionEstimate:{sourceBytes:sum(functionFiles),localLockedDependencyBytes:sum(dependencyFiles),method:'Selective API/reference/local-dependency estimate only; omits other reachable project/build files and builder additions. NOT VALID FOR FUNCTION CAP ACCEPTANCE.'},ceilings:CEILINGS,platform:evidence,hostedReceipt:hosted,...assessment,distPresent:existsSync(path.join(root,'dist')),publicReadiness:'UNRUN'};
}
export function deliveryArgs(args) {
  const o={},names={'--platform-bundle':'platformBundle','--bundle-sha256':'bundleSha256','--expected-project':'projectId','--expected-team':'teamId','--expected-plan':'plan','--delivery-method':'deliveryMethod','--proposed-runtime':'proposedRuntime','--hosted-receipt':'hostedReceipt','--hosted-receipt-sha256':'hostedReceiptSha256','--expected-commit':'commitSha','--expected-tree':'treeSha','--expected-projection-sha256':'projectionSha256','--expected-output-sha256':'outputSha256','--expected-runtime-config-sha256':'runtimeConfigurationSha256','--source-projection':'sourceProjection','--source-projection-sha256':'sourceProjectionSha256'};
  names['--function-bundle']='functionBundle';names['--function-bundle-sha256']='functionBundleSha256';
  for(let i=0;i<args.length;i+=2) {const k=names[args[i]];assert(k && args[i+1] && !o[k],`Unknown/duplicate delivery option ${args[i]}`);o[k]=args[i+1];}
  const pick=(ks)=>Object.fromEntries(ks.map((k)=>[k,o[k]]));
  return {...o,...(o.platformBundle?{expectedTarget:pick(['projectId','teamId','plan','deliveryMethod'])}:{}),...(o.hostedReceipt?{expectedSource:pick(['commitSha','treeSha','projectionSha256','outputSha256','runtimeConfigurationSha256'])}:{})};
}
if(process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const report = deliveryReport(deliveryArgs(process.argv.slice(2)));console.log(JSON.stringify(report,null,2));if(report.failures.length)process.exitCode=1;
}
