import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {verifyPlatformBundle,assessDelivery,verifyHostedReceipt} from '../../../scripts/lib/platform-evidence.mjs';
import {canonical,sha} from '../../../scripts/lib/expansion-contract.mjs';
import {evidenceDir} from './helpers.mjs';

const expected={projectId:'prj_Fixture',teamId:'team_Fixture',plan:'hobby',deliveryMethod:'git'};
const at='2026-10-29T18:35:53.812972+00:00',start='2026-10-29T18:35:00Z',end='2026-10-29T18:35:40Z';
const limitsText='When using the CLI to deploy, the maximum size of the source files that can be uploaded is limited to 100 MB for Hobby and 1 GB for Pro. The maximum number of files that can be uploaded when creating a CLI Deployment is 15,000 for source files. The maximum duration of the Build Step is 45 minutes. Disk Size (GB) 32 32 up to 64 32 up to 64 Although there is no upper limit for output files created during a build, longer build times apply.';
async function fixture(mode='git') {
  const root=await evidenceDir('delivery-CONTRACT-FIXTURE-NOT-HOSTED'),target={...expected,deliveryMethod:mode},data={};
  const team={id:target.teamId,slug:'fixture',plan:'hobby'},project={id:target.projectId,name:'fixture',teamId:target.teamId,framework:'nextjs',nodeVersion:'24.x',gitLink:null};
  for(const [kind,response] of [['team',team],['project',project]]) {
    data[`${kind}-redacted.json`]=`${JSON.stringify(response,null,2)}\n`;
    const route=kind==='team'?`/v2/teams/${target.teamId}`:`/v9/projects/${target.projectId}?teamId=${target.teamId}`;
    data[`${kind}-receipt.json`]=JSON.stringify({kind:'AUTHENTICATED_CLI_READ',argv:['npx.cmd','--offline','--yes','vercel@0.0.0','api',route,'--method','GET','--scope','fixture'],startedAt:start,finishedAt:end,exitCode:0,rawResponseSha256:'0'.repeat(64),retainedRedactedCanonicalSha256:sha(canonical(response)),redactedResponseFile:`${kind}-redacted.json`,redaction:'Automated fixture only; environment values omitted. Raw response not retained.',scope:'fixture',teamId:target.teamId,projectId:target.projectId,observed:response});
  }
  for(const [kind,html] of [['limits',limitsText],['git','Deployment from a Git Repository uses an exact commit.']]) {
    const url=`https://vercel.com/docs/${kind}`;data[`${kind}.html`]=`<html><main>${html}</main></html>`;
    data[`${kind}-receipt.json`]=JSON.stringify({kind:'PRIMARY_DOCUMENT_SNAPSHOT',url,effectiveUrl:url,httpStatus:200,contentType:'text/html; charset=utf-8',startedAt:start,finishedAt:end,argv:['curl.exe','--fail','--silent','--show-error','--location','--max-time','45','--output',`${root}/${kind}.html`,'--write-out','%{http_code}\n%{url_effective}\n%{content_type}',url],snapshotFile:`${kind}.html`,snapshotBytes:Buffer.byteLength(data[`${kind}.html`]),snapshotSha256:sha(data[`${kind}.html`]),claims:'AUTOMATED CONTRACT FIXTURE ONLY'});
  }
  const bundle={schemaVersion:1,createdAt:at,status:'COORDINATOR_READ_EVIDENCE_ONLY',expectedTarget:{projectId:target.projectId,teamId:target.teamId,plan:target.plan,proposedDeliveryMethod:mode},files:Object.entries(data).map(([p,b])=>({path:p,bytes:Buffer.byteLength(b),sha256:sha(b)})),hostedAcceptance:'UNRUN',note:'AUTOMATED FIXTURE; no real hosted receipt'};
  for(const [file,bytes] of Object.entries(data))await writeFile(path.join(root,file),bytes);
  const bundlePath=path.join(root,'BUNDLE.json');await writeFile(bundlePath,JSON.stringify(bundle));
  const options={bundlePath,bundleSha256:sha(JSON.stringify(bundle)),expectedTarget:target};return{root,data,bundle,options,evidence:verifyPlatformBundle(options)};
}
const measurement={metrics:{productBytes:800_000_000,productFiles:5000,distBytes:810_000_000,manifestBytes:2_000_000,functionBytes:40_000_000},sourceUpload:{uncompressedBytes:850_000_000,files:18000},staticFiles:6000,buildDiskEstimateBytes:2_000_000_000};
const functionText='For Python functions , the maximum uncompressed size is 500 MB . Large functions let you deploy uncompressed bundles up to 5 GB . Large functions require fluid compute with Active CPU enabled.';
async function saveFixture(f) {
  for(const [file,b] of Object.entries(f.data))await writeFile(path.join(f.root,file),b);
  f.bundle.files=Object.entries(f.data).map(([p,b])=>({path:p,bytes:Buffer.byteLength(b),sha256:sha(b)}));
  const b=JSON.stringify(f.bundle);await writeFile(f.options.bundlePath,b);f.options.bundleSha256=sha(b);return f;
}
async function withFunctions() {
  const f=await fixture(),url='https://vercel.com/docs/functions/limitations';f.data['functions.html']=`<html><main>${functionText}</main></html>`;
  f.data['functions-receipt.json']=JSON.stringify({kind:'PRIMARY_DOCUMENT_SNAPSHOT',url,effectiveUrl:url,httpStatus:200,contentType:'text/html; charset=utf-8',startedAt:start,finishedAt:end,argv:['curl.exe','--fail','--silent','--show-error','--location','--max-time','45','--output',`${f.root}/functions.html`,'--write-out','%{http_code}\n%{url_effective}\n%{content_type}',url],snapshotFile:'functions.html',snapshotBytes:Buffer.byteLength(f.data['functions.html']),snapshotSha256:sha(f.data['functions.html']),claims:{standardPythonUncompressedFunctionBytes:500_000_000,applicability:'AUTOMATED proposed Python fixture, actual runtime UNRUN',largeFunctionBytes:5_000_000_000,largeFunctionApplicability:'AUTOMATED fixture; never relied on',taskFunctionCeilingBytes:250_000_000,hostedAcceptance:'UNRUN'}});
  return saveFixture(f);
}
test('CLI source caps apply only to CLI; Git retains counts/task ceilings and remains hosted UNRUN',async()=>{
  const git=await fixture(),cli=await fixture('cli');
  const g=assessDelivery({...measurement,evidence:git.evidence});assert(g.failures.every(f=>f.origin==='required-measurement'));assert.equal(g.platformReady,false);assert.equal(g.hostedAcceptance,'UNRUN');assert(g.checks.filter((c)=>['sourceUploadBytes','sourceFiles'].includes(c.metric)).every((c)=>c.status==='NOT_APPLICABLE'));
  const c=assessDelivery({...measurement,evidence:cli.evidence});assert.deepEqual(c.failures.filter(f=>f.origin!=='required-measurement').map((f)=>f.metric),['sourceUploadBytes','sourceFiles']);assert.equal(c.localPromotionValidity,'BLOCKED_LIMIT');
  assert.equal(git.evidence.limits.functionBytes.status,'UNKNOWN');assert.equal(git.evidence.limits.buildDiskBytes.value,32_000_000_000);
  const over=assessDelivery({...measurement,metrics:{...measurement.metrics,productBytes:1_500_000_001},evidence:git.evidence});assert.equal(over.failures[0].origin,'defensive-task-ceiling');
});
test('unmeasured function contents cannot pass task or Python caps through a selective estimate or null coercion',async()=>{
  const f=await withFunctions(),evidence=verifyPlatformBundle({...f.options,proposedRuntime:'python'});
  const report=assessDelivery({...measurement,metrics:{...measurement.metrics,functionBytes:null},evidence});
  assert.equal(report.platformReady,false);assert.equal(report.status,'BLOCKED_UNMEASURED_FUNCTION');
  assert.equal(report.localPromotionValidity,'BLOCKED_UNMEASURED_FUNCTION');
  assert(report.failures.some(f=>f.metric==='functionBytes' && f.origin==='required-measurement'));
  assert(report.checks.filter(c=>['functionBytes','standardPythonFunctionBytes'].includes(c.metric)).every(c=>c.status==='UNRUN_PACKAGE_MEASUREMENT'));
});
test('explicit target, exact retained bytes, receipt/time/normalized schema and applicability cannot be forged by assertions',async()=>{
  for(const mutate of [o=>o.expectedTarget.projectId='prj_Wrong',o=>o.expectedTarget.teamId='team_Wrong',o=>o.expectedTarget.plan='pro',o=>o.expectedTarget.deliveryMethod='cli',o=>o.bundleSha256='0'.repeat(64)]) {const f=await fixture();const o=structuredClone(f.options);mutate(o);assert.throws(()=>verifyPlatformBundle(o));}
  const f=await fixture();await writeFile(path.join(f.root,'limits.html'),'changed');assert.throws(()=>verifyPlatformBundle(f.options),/changed/);
  const unsupported=await fixture();unsupported.bundle.limits={sourceUploadBytes:1_500_000_000};const b=JSON.stringify(unsupported.bundle);await writeFile(unsupported.options.bundlePath,b);assert.throws(()=>verifyPlatformBundle({...unsupported.options,bundleSha256:sha(b)}));
  const noExpected=await fixture();assert.throws(()=>verifyPlatformBundle({...noExpected.options,expectedTarget:undefined}));
});
test('optional ten-file snapshot derives standard Python cap only with explicit proposed applicability; task cap stays stricter',async()=>{
  const f=await withFunctions(),evidence=verifyPlatformBundle({...f.options,proposedRuntime:'python'});
  assert.equal(evidence.limits.functionBytes.value,500_000_000);assert.deepEqual(evidence.limits.functionBytes.runtimes,['python']);assert.equal(evidence.limits.functionBytes.configuration,'STANDARD_UNCOMPRESSED_BUNDLE');assert.equal(evidence.limits.functionBytes.largeFunctions.status,'NOT_RELIED_ON');
  const report=assessDelivery({...measurement,evidence});assert.equal(report.platformReady,false);assert.equal(report.hostedAcceptance,'UNRUN');assert(report.checks.some(c=>c.metric==='standardPythonFunctionBytes' && c.actual===null && c.status==='UNRUN_PACKAGE_MEASUREMENT'));
  const unbound=assessDelivery({...measurement,evidence:verifyPlatformBundle(f.options)});assert(unbound.checks.some(c=>c.metric==='standardPythonFunctionBytes' && c.proposedRuntime==='UNKNOWN' && c.actual===null));assert.equal(unbound.platformReady,false);
  const over=assessDelivery({...measurement,metrics:{...measurement.metrics,functionBytes:300_000_000},evidence});assert(over.failures.some(c=>c.metric==='assertedFunctionBytes' && c.limit===250_000_000));assert(!over.failures.some(c=>c.metric==='assertedStandardPythonFunctionBytes'));
  const overBoth=assessDelivery({...measurement,metrics:{...measurement.metrics,functionBytes:500_000_001},evidence});assert(overBoth.failures.some(c=>c.metric==='assertedStandardPythonFunctionBytes' && c.limit===500_000_000));
  assert.throws(()=>verifyPlatformBundle({...f.options,proposedRuntime:'nodejs'}),/explicit proposed Python/);
  const old=await fixture();assert.equal(verifyPlatformBundle({...old.options,proposedRuntime:'python'}).limits.functionBytes.status,'UNKNOWN');
});
test('function cap cannot come from claims, large-function text, partial names or changed snapshot metadata',async()=>{
  const f=await withFunctions();let receipt=JSON.parse(f.data['functions-receipt.json']);receipt.claims.standardPythonUncompressedFunctionBytes=5_000_000_000;f.data['functions-receipt.json']=JSON.stringify(receipt);await saveFixture(f);assert.throws(()=>verifyPlatformBundle({...f.options,proposedRuntime:'python'}));
  const text=await withFunctions();text.data['functions.html']=text.data['functions.html'].replace('500 MB','5 GB');receipt=JSON.parse(text.data['functions-receipt.json']);receipt.snapshotBytes=Buffer.byteLength(text.data['functions.html']);receipt.snapshotSha256=sha(text.data['functions.html']);text.data['functions-receipt.json']=JSON.stringify(receipt);await saveFixture(text);assert.throws(()=>verifyPlatformBundle(text.options),/supported standard Python size/);
  const partial=await withFunctions();delete partial.data['functions-receipt.json'];await saveFixture(partial);assert.throws(()=>verifyPlatformBundle(partial.options));
  const metadata=await withFunctions();receipt=JSON.parse(metadata.data['functions-receipt.json']);receipt.effectiveUrl='https://fixture.invalid';metadata.data['functions-receipt.json']=JSON.stringify(receipt);await saveFixture(metadata);assert.throws(()=>verifyPlatformBundle(metadata.options));
});
test('READY, booleans, a URL or a branch never establish matching hosted acceptance',async()=>{
  const f=await fixture(),receiptPath=path.join(f.root,'ready-only.json'),bytes=JSON.stringify({status:'READY',verified:true,url:'https://fixture.invalid',branch:'main'});await writeFile(receiptPath,bytes);
  assert.throws(()=>verifyHostedReceipt({receiptPath,receiptSha256:sha(bytes),expectedTarget:expected}));
  const report=assessDelivery({...measurement,evidence:f.evidence});assert.equal(report.platformReady,false);assert.equal(report.status,'BLOCKED_UNMEASURED_FUNCTION');
  for(const hostedReceipt of [true,{status:'READY'},{status:'VERIFIED_MATCHING_RETAINED_HOSTED_RECEIPT',build:{outputBytes:1,functionBytes:1,durationSeconds:1,diskBytes:1}}]) assert.throws(()=>assessDelivery({...measurement,evidence:f.evidence,hostedReceipt}),/must pass local retained-file consistency/);
});
test('mutually consistent fabricated hosted files remain asserted, including plausible hashes/metrics/target/source',async()=>{
  const f=await fixture(),expectedSource={commitSha:'1'.repeat(40),treeSha:'2'.repeat(40),projectionSha256:'3'.repeat(64),outputSha256:'4'.repeat(64),runtimeConfigurationSha256:'5'.repeat(64)};
  // Deliberately synthetic contract fixture; never an actual deployment receipt.
  const receipt={schemaVersion:1,kind:'ACTUAL_VERCEL_BUILD_DEPLOYMENT',observedAt:at,target:expected,source:{commitSha:expectedSource.commitSha,treeSha:expectedSource.treeSha,projectionSha256:expectedSource.projectionSha256},deploymentId:'dpl_Fixture',buildId:'AUTOMATED-CONTRACT-FIXTURE-NOT-HOSTED',build:{status:'SUCCEEDED',outputSha256:expectedSource.outputSha256,outputBytes:810_000_000,staticFiles:6000,functionBytes:40_000_000,durationSeconds:120,diskBytes:2_000_000_000},runtimeConfiguration:{sha256:expectedSource.runtimeConfigurationSha256,status:'VERIFIED_ACTUAL_DEPLOYMENT'}};
  const observed={projectId:expected.projectId,teamId:expected.teamId,plan:'hobby',deliveryMethod:'git',source:receipt.source,deploymentId:receipt.deploymentId,buildId:receipt.buildId,readyState:'READY',build:receipt.build,runtimeConfiguration:receipt.runtimeConfiguration};
  const read={kind:'AUTHENTICATED_CLI_READ',startedAt:start,finishedAt:end,tool:'vercel@65.11.0',method:'GET',route:`/v13/deployments/${receipt.deploymentId}?teamId=${expected.teamId}`,exitCode:0,rawResponseSha256:sha('fabricated raw provider response'),retainedRedactedCanonicalSha256:sha(canonical(observed)),redaction:'AUTOMATED FIXTURE; Raw response not retained',observed};
  const readBytes=JSON.stringify(read);await writeFile(path.join(f.root,'hosted-read.json'),readBytes);receipt.retainedRead={path:'hosted-read.json',bytes:Buffer.byteLength(readBytes),sha256:sha(readBytes)};
  const receiptPath=path.join(f.root,'hosted-contract-fixture.json'),bytes=JSON.stringify(receipt);await writeFile(receiptPath,bytes);
  const options={receiptPath,receiptSha256:sha(bytes),expectedTarget:expected,expectedSource};
  const hosted=verifyHostedReceipt(options);assert.equal(hosted.status,'ASSERTED_HOSTED_RECEIPT_CONSISTENCY_ONLY');
  assert.equal(hosted.providerProvenance,'UNRUN');assert.equal(hosted.functionBytes,null);assert.equal(hosted.hostedAcceptance,'UNRUN');
  const assessed=assessDelivery({...measurement,evidence:f.evidence,hostedReceipt:hosted});
  assert.equal(assessed.platformReady,false);assert.equal(assessed.hostedAcceptance,'UNRUN');assert.equal(assessed.functionMeasurement.actualBytes,null);assert.equal(assessed.functionGate,'BLOCKED_UNMEASURED_FUNCTION');
  for(const field of Object.keys(expectedSource)) assert.throws(()=>verifyHostedReceipt({...options,expectedSource:{...expectedSource,[field]:(field.endsWith('Sha')?'a'.repeat(40):'a'.repeat(64))}}));
  assert.throws(()=>verifyHostedReceipt({...options,expectedTarget:{...expected,projectId:'prj_Wrong'}}));
  receipt.build.functionBytes=600_000_000;read.retainedRedactedCanonicalSha256=sha(canonical(observed));
  const overRead=JSON.stringify(read);await writeFile(path.join(f.root,'hosted-read.json'),overRead);receipt.retainedRead={...receipt.retainedRead,bytes:Buffer.byteLength(overRead),sha256:sha(overRead)};
  const overReceipt=JSON.stringify(receipt);await writeFile(receiptPath,overReceipt);
  const over=assessDelivery({...measurement,evidence:f.evidence,hostedReceipt:verifyHostedReceipt({...options,receiptSha256:sha(overReceipt)})});
  assert(over.failures.some(f=>f.metric==='assertedHostedFunctionBytes' && f.actual===null && f.limit===250_000_000));assert.equal(over.platformReady,false);assert.equal(over.hostedAcceptance,'UNRUN');
  read.retainedRedactedCanonicalSha256='0'.repeat(64);const changed=JSON.stringify(read);await writeFile(path.join(f.root,'hosted-read.json'),changed);receipt.retainedRead={...receipt.retainedRead,bytes:Buffer.byteLength(changed),sha256:sha(changed)};const changedReceipt=JSON.stringify(receipt);await writeFile(receiptPath,changedReceipt);
  assert.throws(()=>verifyHostedReceipt({...options,receiptSha256:sha(changedReceipt)}),/Normalized hosted read changed/);
});
test('direct/prospective callers cannot turn numbers, null arithmetic or positive options into actual function authority',async()=>{
  const f=await fixture();
  for(const value of [null,0,1,40_000_000,null+8192,250_000_000]) {
    const result=assessDelivery({...measurement,metrics:{...measurement.metrics,functionBytes:value},evidence:f.evidence,platformReady:true,hostedAcceptance:'PASSED',complete:true,verified:true});
    assert.equal(result.functionMeasurement.actualBytes,null);assert.equal(result.functionMeasurement.suppliedBytes,value);assert.equal(result.functionGate,'BLOCKED_UNMEASURED_FUNCTION');
    assert.equal(result.platformReady,false);assert.equal(result.hostedAcceptance,'UNRUN');assert.equal(result.localPromotionValidity,'BLOCKED_UNMEASURED_FUNCTION');
  }
});
test('real coordinator bundle pins retained bytes against the separately supplied work-order target', {skip:!process.env.FURNITUREOS_PLATFORM_EVIDENCE_BUNDLE},async()=>{
  const bundlePath=process.env.FURNITUREOS_PLATFORM_EVIDENCE_BUNDLE,bundleSha256=sha(await readFile(bundlePath));
  const evidence=verifyPlatformBundle({bundlePath,bundleSha256,expectedTarget:{projectId:'prj_G7zuwN0gXA3nBD6QtC1hOncmMGV1',teamId:'team_pSuxCVzi76D0eTIqAWcqv9eX',plan:'hobby',deliveryMethod:'git'}});
  assert.equal(evidence.verified.targetMetadata.gitLink,null);assert.equal(evidence.limits.cliSourceBytes.value,100_000_000);assert.equal(evidence.limits.cliSourceFiles.value,15000);assert.equal(evidence.unknown.actualHostedDeployment,'UNRUN');
});
test('real ten-file coordinator bundle adds exactly pinned standard Python evidence and preserves old target documents', {skip:!process.env.FURNITUREOS_PLATFORM_EVIDENCE_BUNDLE_2},async()=>{
  const bundlePath=process.env.FURNITUREOS_PLATFORM_EVIDENCE_BUNDLE_2,bundleSha256='3eda7b4f8c58c86fc4b1b77b91e26938840f6bf5490ddc39b2bbd4a0263b6bfd';
  const evidence=verifyPlatformBundle({bundlePath,bundleSha256,proposedRuntime:'python',expectedTarget:{projectId:'prj_G7zuwN0gXA3nBD6QtC1hOncmMGV1',teamId:'team_pSuxCVzi76D0eTIqAWcqv9eX',plan:'hobby',deliveryMethod:'git'}});
  assert.equal(evidence.limits.functionBytes.value,500_000_000);assert.equal(evidence.limits.functionBytes.actualRuntime,'UNRUN');assert.equal(evidence.verified.targetMetadata.gitLink,null);
  const older=JSON.parse(await readFile(path.join(path.dirname(bundlePath),'../platform-evidence-1/BUNDLE.json')));assert.deepEqual(evidence.verified.retainedFiles.slice(0,8),older.files);
});
