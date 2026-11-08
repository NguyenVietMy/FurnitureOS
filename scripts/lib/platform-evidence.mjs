// Retained coordinator receipts are evidence of recorded reads, not a live audit.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {keys,pin,sha,canonical,noLinkedPath} from './expansion-contract.mjs';

export const TASK_CEILINGS = {productBytes:1_500_000_000,productFiles:25_000,distBytes:1_600_000_000,manifestBytes:20_000_000,functionBytes:250_000_000};
const NAMED = ['team-receipt.json','team-redacted.json','project-receipt.json','project-redacted.json','limits-receipt.json','limits.html','git-receipt.json','git.html'];
const FUNCTION_NAMES = ['functions-receipt.json','functions.html'];
const consistentHostedDiagnostics = new WeakSet();
const iso = (v) => {assert(typeof v==='string' && /^\d{4}-\d\d-\d\dT/.test(v) && Number.isFinite(Date.parse(v)),'Invalid evidence time');return Date.parse(v);};
function target(t) {
  keys(t,['projectId','teamId','plan','deliveryMethod']);
  assert(/^prj_[A-Za-z0-9]+$/.test(t.projectId) && /^team_[A-Za-z0-9]+$/.test(t.teamId));
  assert(t.plan==='hobby','Only the reviewed Hobby evidence contract is supported');
  assert(['cli','git'].includes(t.deliveryMethod));return t;
}
function raw(file,maximum=3_000_000) {const b=readFileSync(noLinkedPath(file));assert(b.length>0 && b.length<=maximum,'Evidence file size bound');return b;}
function json(file) {return JSON.parse(raw(file).toString('utf8'));}
function digestFile(root,file,p) {
  assert([...NAMED,...FUNCTION_NAMES].includes(file),'Unknown receipt/source name');
  const b=raw(path.join(root,file));assert.equal(b.length,p.bytes,'Evidence byte count changed');assert.equal(sha(b),pin(p.sha256),'Evidence digest changed');return b;
}
export function documentText(rawHtml) {
  return rawHtml.toString('utf8').replace(/<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>/gi,' ').replace(/<[^>]*>/g,' ')
    .replace(/&#x([a-f0-9]+);/gi,(_,h)=>String.fromCodePoint(parseInt(h,16))).replace(/&#(\d+);/g,(_,n)=>String.fromCodePoint(Number(n)))
    .replace(/&nbsp;/g,' ').replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/\s+/g,' ').trim();
}
function recordedRead(receipt,response,expected,kind,observedAt) {
  keys(receipt,['kind','argv','startedAt','finishedAt','exitCode','rawResponseSha256','retainedRedactedCanonicalSha256','redactedResponseFile','redaction','scope','teamId','projectId','observed']);
  assert.equal(receipt.kind,'AUTHENTICATED_CLI_READ');assert.equal(receipt.exitCode,0);
  assert.equal(receipt.projectId,expected.projectId);assert.equal(receipt.teamId,expected.teamId);
  assert(iso(receipt.startedAt)<=iso(receipt.finishedAt) && iso(receipt.finishedAt)<=iso(observedAt),'Read time outside retained bundle');
  assert(typeof receipt.redaction==='string' && receipt.redaction.includes('Raw response not retained') && receipt.redaction.includes('environment values omitted'),'Missing redaction limit');
  pin(receipt.rawResponseSha256);assert.equal(receipt.retainedRedactedCanonicalSha256,sha(canonical(response)),'Normalized redacted response changed');
  assert.deepEqual(receipt.observed,response);assert.equal(receipt.redactedResponseFile,`${kind}-redacted.json`);
  const route=kind==='team'?`/v2/teams/${expected.teamId}`:`/v9/projects/${expected.projectId}?teamId=${expected.teamId}`;
  const a=receipt.argv;assert(Array.isArray(a) && a.length===10);
  assert.deepEqual(a.slice(0,3),['npx.cmd','--offline','--yes']);assert(/^vercel@\d+\.\d+\.\d+$/.test(a[3]));
  assert.deepEqual(a.slice(4),['api',route,'--method','GET','--scope',receipt.scope]);
  assert(/^[a-z0-9-]+$/.test(receipt.scope));
}
function snapshot(receipt,bytes,name,url,observedAt) {
  keys(receipt,['kind','url','effectiveUrl','httpStatus','contentType','startedAt','finishedAt','argv','snapshotFile','snapshotBytes','snapshotSha256','claims']);
  assert.equal(receipt.kind,'PRIMARY_DOCUMENT_SNAPSHOT');assert.equal(receipt.url,url);assert.equal(receipt.effectiveUrl,url);assert.equal(receipt.httpStatus,200);assert.equal(receipt.contentType,'text/html; charset=utf-8');
  assert(iso(receipt.startedAt)<=iso(receipt.finishedAt) && iso(receipt.finishedAt)<=iso(observedAt));
  assert.equal(receipt.snapshotFile,name);assert.equal(receipt.snapshotBytes,bytes.length);assert.equal(receipt.snapshotSha256,sha(bytes));
  // The output pathname is recorded but never used for reading. Only named,
  // hash-bound local bundle files above can supply retained evidence.
  const a=receipt.argv;assert(Array.isArray(a) && a.length===12);
  assert.deepEqual(a.slice(0,8),['curl.exe','--fail','--silent','--show-error','--location','--max-time','45','--output']);
  assert(typeof a[8]==='string' && a[8].replaceAll('\\','/').endsWith(`/${name}`));
  assert.deepEqual(a.slice(9),['--write-out','%{http_code}\n%{url_effective}\n%{content_type}',url]);
}
export function verifyPlatformBundle({bundlePath,bundleSha256,expectedTarget,proposedRuntime}) {
  assert(proposedRuntime===undefined || proposedRuntime==='python','Only explicit proposed Python runtime applicability is supported');
  target(expectedTarget);pin(bundleSha256);const bytes=raw(bundlePath,100_000);assert.equal(sha(bytes),bundleSha256,'Bundle SHA256 changed');
  const bundle=JSON.parse(bytes);keys(bundle,['schemaVersion','createdAt','status','expectedTarget','files','hostedAcceptance','note']);
  assert.equal(bundle.schemaVersion,1);assert.equal(bundle.status,'COORDINATOR_READ_EVIDENCE_ONLY');assert.equal(bundle.hostedAcceptance,'UNRUN');iso(bundle.createdAt);
  keys(bundle.expectedTarget,['projectId','teamId','plan','proposedDeliveryMethod']);
  assert.deepEqual(bundle.expectedTarget,{projectId:expectedTarget.projectId,teamId:expectedTarget.teamId,plan:expectedTarget.plan,proposedDeliveryMethod:expectedTarget.deliveryMethod});
  assert.equal(bundle.expectedTarget.proposedDeliveryMethod,expectedTarget.deliveryMethod,'Delivery method does not match the reviewed expected target');
  assert(Array.isArray(bundle.files) && [8,10].includes(bundle.files.length) && new Set(bundle.files.map((f)=>f.path)).size===bundle.files.length);
  const names=bundle.files.length===10?[...NAMED,...FUNCTION_NAMES]:NAMED;
  const root=path.dirname(path.resolve(bundlePath)),retained={};
  for(const f of bundle.files) {keys(f,['path','bytes','sha256']);assert(Number.isSafeInteger(f.bytes) && f.bytes>0);retained[f.path]=digestFile(root,f.path,f);}
  assert.deepEqual(Object.keys(retained).sort(),[...names].sort());
  const team=JSON.parse(retained['team-redacted.json']),project=JSON.parse(retained['project-redacted.json']);
  keys(team,['id','slug','plan']);keys(project,['id','name','teamId','framework','nodeVersion','gitLink']);
  assert(typeof team.slug==='string' && /^[a-z0-9-]{1,100}$/.test(team.slug));
  assert(typeof project.name==='string' && /^[a-z0-9-]{1,100}$/.test(project.name));
  assert(project.framework===null || (typeof project.framework==='string' && /^[a-z0-9-]{1,50}$/.test(project.framework)));
  assert(typeof project.nodeVersion==='string' && /^\d{1,3}\.(?:x|\d{1,3}(?:\.\d{1,3})?)$/.test(project.nodeVersion));
  assert.equal(team.id,expectedTarget.teamId);assert.equal(team.plan,expectedTarget.plan);assert.equal(project.id,expectedTarget.projectId);assert.equal(project.teamId,expectedTarget.teamId);
  assert(project.gitLink===null,'An updated Git connection receipt needs an explicit reviewed schema; do not infer connection from arbitrary fields');
  recordedRead(JSON.parse(retained['team-receipt.json']),team,expectedTarget,'team',bundle.createdAt);
  recordedRead(JSON.parse(retained['project-receipt.json']),project,expectedTarget,'project',bundle.createdAt);
  snapshot(JSON.parse(retained['limits-receipt.json']),retained['limits.html'],'limits.html','https://vercel.com/docs/limits',bundle.createdAt);
  snapshot(JSON.parse(retained['git-receipt.json']),retained['git.html'],'git.html','https://vercel.com/docs/git',bundle.createdAt);
  const limits=documentText(retained['limits.html']),git=documentText(retained['git.html']);
  const cliBytes=/When using the CLI to deploy, the maximum size of the source files that can be uploaded is limited to 100 MB for Hobby and 1 GB for Pro\./.exec(limits);
  const cliFiles=/maximum number of files that can be uploaded when creating a CLI Deployment is 15,000 for source files\./.exec(limits);
  const buildTime=/maximum duration of the Build Step is 45 minutes\./.exec(limits);
  const disk=/Disk Size \(GB\) 32 32 up to 64 32 up to 64/.exec(limits);
  const outputFiles=/Although there is no upper limit for output files created during a build/.exec(limits);
  assert(cliBytes && cliFiles && buildTime,'Retained primary snapshot does not establish the supported limits');
  assert(/Git Repository|Git repository|GitHub/.test(git) && /commit/i.test(git),'Retained Git documentation does not establish Git-reference delivery');
  const fact=(value,unit,applicability,quote)=>({status:'VERIFIED_RETAINED_DOCUMENT',value,unit,origin:'documented-platform-limit',applicability,source:'limits.html',quote});
  let functionBytes={status:'UNKNOWN',origin:'documented-platform-limit',reason:'Historical eight-file bundle has no retained function-size snapshot'};
  if(retained['functions.html']) {
    const receipt=JSON.parse(retained['functions-receipt.json']);
    snapshot(receipt,retained['functions.html'],'functions.html','https://vercel.com/docs/functions/limitations',bundle.createdAt);
    keys(receipt.claims,['standardPythonUncompressedFunctionBytes','applicability','largeFunctionBytes','largeFunctionApplicability','taskFunctionCeilingBytes','hostedAcceptance']);
    assert(typeof receipt.claims.applicability==='string' && receipt.claims.applicability.length<=1000 && typeof receipt.claims.largeFunctionApplicability==='string' && receipt.claims.largeFunctionApplicability.length<=1000);
    const text=documentText(retained['functions.html']);
    const standard=/For Python functions\s*, the maximum uncompressed size is (\d+) MB\s*\./.exec(text);
    const large=/Large functions let you deploy uncompressed bundles up to (\d+) GB\s*\./.exec(text);
    assert(standard && standard[1]==='500','Retained primary snapshot does not establish the supported standard Python size');
    assert(large && large[1]==='5' && /Large functions require fluid compute with Active CPU enabled\./.test(text),'Unsupported large-function documentation; never infer eligibility');
    const value=Number(standard[1])*1_000_000;
    assert.equal(receipt.claims.standardPythonUncompressedFunctionBytes,value);assert.equal(receipt.claims.largeFunctionBytes,Number(large[1])*1_000_000_000);
    assert.equal(receipt.claims.taskFunctionCeilingBytes,TASK_CEILINGS.functionBytes);assert.equal(receipt.claims.hostedAcceptance,'UNRUN');
    functionBytes={...fact(value,'uncompressed-bytes',['cli','git'],standard[0]),source:'functions.html',runtimes:['python'],proposedRuntime:proposedRuntime??'UNKNOWN',actualRuntime:'UNRUN',configuration:'STANDARD_UNCOMPRESSED_BUNDLE',largeFunctions:{status:'NOT_RELIED_ON',eligibility:'UNRUN',configuration:'UNRUN'}};
  }
  return {schemaVersion:1,receiptVariant:names.length===10?'TARGET_LIMITS_GIT_STANDARD_PYTHON':'TARGET_LIMITS_GIT',bundleSha256,observedAt:bundle.createdAt,expectedTarget,proposedRuntime:proposedRuntime??'UNKNOWN',evidenceAuthority:'COORDINATOR_READ_RECEIPTS_NOT_INDEPENDENT_HOSTED_AUDIT',
    asserted:{rawAuthenticatedResponseDigests:'ASSERTED_RAW_RESPONSES_NOT_RETAINED',planBuildDiskBytes:23_000_000_000},
    verified:{targetMetadata:project,teamMetadata:team,retainedFiles:bundle.files,sourceSnapshots:'HASH_VERIFIED'},
    limits:{cliSourceBytes:fact(100_000_000,'bytes',['cli'],cliBytes[0]),cliSourceFiles:fact(15_000,'files',['cli'],cliFiles[0]),buildDurationSeconds:fact(2700,'seconds',['cli','git'],buildTime[0]),
      buildDiskBytes:disk?fact(32_000_000_000,'bytes',['cli','git'],disk[0]):{status:'UNKNOWN',origin:'documented-platform-limit',reason:'No supported disk row in retained snapshot'},
      functionBytes,
      outputFiles:outputFiles?{status:'NO_FIXED_LIMIT_IN_RETAINED_DOCUMENT',origin:'documented-platform-limit',applicability:['cli','git'],source:'limits.html',quote:outputFiles[0],reason:'Actual build time/storage acceptance remains unrun'}:{status:'UNKNOWN',origin:'documented-platform-limit',reason:'No supported output-file-count statement in retained snapshot'}},
    discrepancies:disk?[{asserted:'23 GB Hobby build disk in plan prose',retained:'32 GB first disk table value in limits.html',disposition:'Use retained document table; actual build-machine allocation remains unobserved'}]:[],
    unknown:{actualBuildMachineAllocation:true,gitConnection:'UNCONNECTED_AT_RECORDED_OBSERVATION',actualFunctionRuntime:'UNRUN',actualHostedBuild:'UNRUN',actualHostedDeployment:'UNRUN',runtimeConfigurationAcceptance:'UNRUN'}};
}

// Local receipt consistency only. These caller-authored files cannot establish
// provider origin, including when their labels and hashes look authentic.
export function verifyHostedReceipt({receiptPath,receiptSha256,expectedTarget,expectedSource}) {
  target(expectedTarget);assert(expectedSource,'Exact authorized source binding required');
  keys(expectedSource,['commitSha','treeSha','projectionSha256','outputSha256','runtimeConfigurationSha256']);
  for(const k of ['commitSha','treeSha']) assert(/^[a-f0-9]{40}$/.test(expectedSource[k]));
  for(const k of ['projectionSha256','outputSha256','runtimeConfigurationSha256']) pin(expectedSource[k]);
  const bytes=raw(receiptPath,100_000);assert.equal(sha(bytes),pin(receiptSha256));const r=JSON.parse(bytes);
  keys(r,['schemaVersion','kind','observedAt','target','source','deploymentId','buildId','build','runtimeConfiguration','retainedRead']);
  assert.equal(r.schemaVersion,1);assert.equal(r.kind,'ACTUAL_VERCEL_BUILD_DEPLOYMENT');iso(r.observedAt);assert.deepEqual(r.target,expectedTarget);
  assert.deepEqual(r.source,{commitSha:expectedSource.commitSha,treeSha:expectedSource.treeSha,projectionSha256:expectedSource.projectionSha256});
  assert(/^dpl_[A-Za-z0-9]+$/.test(r.deploymentId) && typeof r.buildId==='string' && r.buildId.length>0);
  keys(r.build,['status','outputSha256','outputBytes','staticFiles','functionBytes','durationSeconds','diskBytes']);
  assert.equal(r.build.status,'SUCCEEDED');assert.equal(r.build.outputSha256,expectedSource.outputSha256);
  for(const k of ['outputBytes','staticFiles','functionBytes','durationSeconds','diskBytes']) assert(Number.isSafeInteger(r.build[k]) && r.build[k]>0);
  assert.deepEqual(r.runtimeConfiguration,{sha256:expectedSource.runtimeConfigurationSha256,status:'VERIFIED_ACTUAL_DEPLOYMENT'});
  keys(r.retainedRead,['path','bytes','sha256']);assert(/^[a-z0-9-]+\.json$/.test(r.retainedRead.path),'Named retained build/deployment read required');
  const b=raw(path.join(path.dirname(path.resolve(receiptPath)),r.retainedRead.path));assert.equal(b.length,r.retainedRead.bytes);assert.equal(sha(b),pin(r.retainedRead.sha256));const read=JSON.parse(b);
  keys(read,['kind','startedAt','finishedAt','tool','method','route','exitCode','rawResponseSha256','retainedRedactedCanonicalSha256','redaction','observed']);
  assert.equal(read.kind,'AUTHENTICATED_CLI_READ');assert.equal(read.exitCode,0);assert.equal(read.method,'GET');assert.equal(read.route,`/v13/deployments/${r.deploymentId}?teamId=${expectedTarget.teamId}`);
  assert(typeof read.tool==='string' && /^vercel@\d+\.\d+\.\d+$/.test(read.tool));pin(read.rawResponseSha256);assert(typeof read.redaction==='string' && read.redaction.includes('Raw response not retained'));
  assert(iso(read.startedAt)<=iso(read.finishedAt) && iso(read.finishedAt)<=iso(r.observedAt));
  assert.deepEqual(read.observed,{projectId:expectedTarget.projectId,teamId:expectedTarget.teamId,plan:expectedTarget.plan,deliveryMethod:expectedTarget.deliveryMethod,source:r.source,deploymentId:r.deploymentId,buildId:r.buildId,readyState:'READY',build:r.build,runtimeConfiguration:r.runtimeConfiguration});
  assert.equal(read.retainedRedactedCanonicalSha256,sha(canonical(read.observed)),'Normalized hosted read changed');
  const result={status:'ASSERTED_HOSTED_RECEIPT_CONSISTENCY_ONLY',receiptSha256,
    evidenceAuthority:'LOCAL_JSON_PROVIDER_PROVENANCE_UNESTABLISHED',
    asserted:{deploymentId:r.deploymentId,buildId:r.buildId,target:r.target,source:r.source,build:r.build,runtimeConfiguration:r.runtimeConfiguration,rawResponseSha256:read.rawResponseSha256},
    verified:{retainedFileHashes:true,normalizedConsistency:true,expectedBindingsMatch:true},
    functionBytes:null,providerProvenance:'UNRUN',hostedAcceptance:'UNRUN',platformReady:false};
  consistentHostedDiagnostics.add(result);return result;
}

export function assessDelivery({metrics,sourceUpload,staticFiles,buildDiskEstimateBytes,evidence,hostedReceipt}) {
  assert(!hostedReceipt || consistentHostedDiagnostics.has(hostedReceipt),'Hosted diagnostic must pass local retained-file consistency checks; no provider authority is established');
  const checks=[],failures=[];
  const suppliedFunctionBytes=metrics.functionBytes??null;
  assert(suppliedFunctionBytes===null || (Number.isSafeInteger(suppliedFunctionBytes) && suppliedFunctionBytes>=0));
  const assertedThreshold=(metric,value,limit,origin)=>{
    const over=value>limit;
    checks.push({metric,actual:null,assertedValue:value,limit,origin,status:over?'ASSERTED_LIMIT_EXCEEDED':'ASSERTED_VALUE_WITHIN_LIMIT_NOT_MEASUREMENT'});
    if(over)failures.push({metric,actual:null,assertedValue:value,limit,origin});
  };
  for(const [metric,limit] of Object.entries(TASK_CEILINGS)) {
    if(metric==='functionBytes') {
      checks.push({metric,actual:null,limit,origin:'defensive-task-ceiling',applicability:['cli','git'],status:'UNRUN_PACKAGE_MEASUREMENT'});
      failures.push({metric,actual:null,limit,origin:'required-measurement',reason:'Offline files and caller-supplied numbers do not establish complete function invocation/output provenance'});
      if(suppliedFunctionBytes!==null)assertedThreshold('assertedFunctionBytes',suppliedFunctionBytes,limit,'unverified-function-claim');
      continue;
    }
    assert(Number.isSafeInteger(metrics[metric]) && metrics[metric]>=0);const pass=metrics[metric]<=limit;checks.push({metric,actual:metrics[metric],limit,origin:'defensive-task-ceiling',applicability:['cli','git'],status:pass?'WITHIN_TASK_CEILING':'BLOCKED'});if(!pass) failures.push({metric,actual:metrics[metric],limit,origin:'defensive-task-ceiling'});
  }
  const mode=evidence?.expectedTarget.deliveryMethod;
  for(const [metric,actual,key] of [['sourceUploadBytes',sourceUpload.uncompressedBytes,'cliSourceBytes'],['sourceFiles',sourceUpload.files,'cliSourceFiles']]) {
    const fact=evidence?.limits[key],status=!evidence?'UNRUN_EVIDENCE':mode==='git'?'NOT_APPLICABLE':actual<=fact.value?'WITHIN_DOCUMENTED_CLI_LIMIT':'BLOCKED';
    checks.push({metric,actual,limit:fact?.value ?? null,origin:'documented-platform-limit',applicability:['cli'],status});if(status==='BLOCKED') failures.push({metric,actual,limit:fact.value,origin:'documented-platform-limit'});
  }
  if(evidence?.limits.buildDiskBytes.status==='VERIFIED_RETAINED_DOCUMENT') {const limit=evidence.limits.buildDiskBytes.value;checks.push({metric:'buildDiskEstimateBytes',actual:buildDiskEstimateBytes,limit,origin:'documented-platform-limit',applicability:['cli','git'],status:buildDiskEstimateBytes<=limit?'ESTIMATE_WITHIN_DOCUMENTED_TABLE_LIMIT_ACTUAL_UNRUN':'BLOCKED'});if(buildDiskEstimateBytes>limit)failures.push({metric:'buildDiskEstimateBytes',actual:buildDiskEstimateBytes,limit});}
  const functionCap=evidence?.limits.functionBytes;
  if(functionCap?.status==='VERIFIED_RETAINED_DOCUMENT') {
    const applicable=evidence.proposedRuntime==='python',limit=functionCap.value;
    checks.push({metric:'standardPythonFunctionBytes',actual:null,limit,origin:'documented-platform-limit',applicability:['cli','git'],runtimes:['python'],proposedRuntime:evidence.proposedRuntime,actualRuntime:'UNRUN',status:'UNRUN_PACKAGE_MEASUREMENT'});
    if(applicable && suppliedFunctionBytes!==null)assertedThreshold('assertedStandardPythonFunctionBytes',suppliedFunctionBytes,limit,'unverified-function-claim');
  }
  if(hostedReceipt) {
    const claim=hostedReceipt.asserted.build;
    for(const [metric,value,limit] of [['assertedHostedFunctionBytes',claim.functionBytes,TASK_CEILINGS.functionBytes],['assertedHostedDistBytes',claim.outputBytes,TASK_CEILINGS.distBytes],['assertedHostedBuildDurationSeconds',claim.durationSeconds,evidence?.limits.buildDurationSeconds.value],['assertedHostedBuildDiskBytes',claim.diskBytes,evidence?.limits.buildDiskBytes.value]]) {
      if(limit!==undefined)assertedThreshold(metric,value,limit,'unverified-hosted-claim');
    }
  }
  const blocked=failures.some(f=>f.origin!=='required-measurement')?'BLOCKED_LIMIT':'BLOCKED_UNMEASURED_FUNCTION';
  return {checks,failures,staticFiles,deliveryMethod:mode ?? 'UNKNOWN',localPromotionValidity:blocked,
    functionMeasurement:{actualBytes:null,status:'UNKNOWN',suppliedBytes:suppliedFunctionBytes,authority:'UNESTABLISHED'},functionGate:'BLOCKED_UNMEASURED_FUNCTION',
    platformReady:false,hostedAcceptance:'UNRUN',hostedDiagnostic:hostedReceipt??null,
    status:blocked,evidenceAuthority:'OFFLINE_DIAGNOSTICS_ONLY',
    unknownPlatformLimits:Object.fromEntries(Object.entries(evidence?.limits??{functionBytes:{status:'UNKNOWN'}}).filter(([,v])=>v.status==='UNKNOWN')),authorization:'NO_PUBLICATION_DEPLOYMENT_OR_PROMOTION_AUTHORITY_GRANTED'};
}
