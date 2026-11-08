import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile,unlink} from 'node:fs/promises';
import path from 'node:path';
import {pythonFunctionPolicy,verifyFunctionBundle} from '../../../scripts/lib/function-bundle.mjs';
import {REPO_ROOT} from '../../../scripts/lib/paths.mjs';
import {assessDelivery} from '../../../scripts/lib/platform-evidence.mjs';
import {sha} from '../../../scripts/lib/expansion-contract.mjs';
import {evidenceDir} from './helpers.mjs';

// Fault-injection contract fixtures, never an actual builder/deployment receipt.
async function fixture() {
  const dir=await evidenceDir('FUNCTION-BUNDLE-SYNTHETIC-CONTRACT-ONLY'),root=path.join(dir,'source'),output=path.join(dir,'output'),bundle=path.join(output,'bundle');
  const config={functions:{'api/**':{includeFiles:'{api/**,public/style-references/**}',excludeFiles:'dist/**'}}};
  const payload={'api/index.py':'# fixture','api/main.py':'# fixture app export','api/catalogue/providers/expansion/index.json':'{}','public/style-references/ref-01.jpg':'fixture-reference','pyproject.toml':'# fixture','uv.lock':'# fixture','_vendor/dependency.py':'# fixture dependency'};
  for(const [name,data] of Object.entries(payload)) {
    for(const base of [bundle,...(name.startsWith('_vendor/')?[]:[root])]) {
      const file=path.join(base,name);await mkdir(path.dirname(file),{recursive:true});await writeFile(file,data);
    }
  }
  await writeFile(path.join(root,'vercel.json'),JSON.stringify(config));
  const report={schemaVersion:1,kind:'FUNCTION_FILE_INVENTORY',builder:{name:'@vercel/python',version:'30.1.0'},runtime:'python3.12',entrypoint:'api/index.py',config,records:Object.entries(payload).map(([p,b])=>({path:p,bytes:Buffer.byteLength(b),sha256:sha(b)}))};
  const bundlePath=path.join(output,'BUNDLE.json');
  async function save(){report.files=report.records.length;report.totalBytes=report.records.reduce((n,r)=>n+r.bytes,0);const b=JSON.stringify(report);await writeFile(bundlePath,b);return{bundlePath,bundleSha256:sha(b),root};}
  return {root,bundle,report,save,options:await save()};
}
test('local inventory checks byte/input consistency without establishing complete builder output',async()=>{
  const f=await fixture(),diagnostic=verifyFunctionBundle(f.options);
  assert.equal(diagnostic.inventory.bytes,f.report.totalBytes);assert.equal(diagnostic.status,'DIAGNOSTIC_LOCAL_FILE_INVENTORY');
  assert.equal(diagnostic.functionBytes,null);assert.equal(diagnostic.dependencyClosure,'UNKNOWN');assert.equal(diagnostic.builderInvocation,'UNRUN');assert.equal(diagnostic.platformReady,false);
  await unlink(path.join(f.bundle,'api/catalogue/providers/expansion/index.json'));assert.throws(()=>verifyFunctionBundle(f.options),/inventory changed/);
  const missing=await fixture();missing.report.records=missing.report.records.filter(r=>!r.path.includes('expansion'));await unlink(path.join(missing.bundle,'api/catalogue/providers/expansion/index.json'));
  const missingOptions=await missing.save();assert.throws(()=>verifyFunctionBundle(missingOptions),/Missing runtime input/);
  const source=await fixture();await writeFile(path.join(source.root,'api/index.py'),'# changed');assert.throws(()=>verifyFunctionBundle(source.options),/input changed/);
  const config=await fixture();await writeFile(path.join(config.root,'vercel.json'),'{}');assert.throws(()=>verifyFunctionBundle(config.options));
  const model=await fixture();model.report.kind='SIMULATED_FILTER_ONLY';const modelOptions=await model.save();assert.equal(verifyFunctionBundle(modelOptions).functionBytes,null);
});
test('inventory detects duplicated static payload, unexpected files and byte/hash drift',async()=>{
  const f=await fixture(),data='unwanted static payload';await mkdir(path.join(f.bundle,'dist'),{recursive:true});await writeFile(path.join(f.bundle,'dist/index.html'),data);
  f.report.records.push({path:'dist/index.html',bytes:Buffer.byteLength(data),sha256:sha(data)});const staticOptions=await f.save();assert.throws(()=>verifyFunctionBundle(staticOptions),/Static or development payload/);
  const extra=await fixture();await writeFile(path.join(extra.bundle,'orphan.py'),'# extra');assert.throws(()=>verifyFunctionBundle(extra.options),/inventory changed/);
  const changed=await fixture();await writeFile(path.join(changed.bundle,'api/index.py'),'# changed');assert.throws(()=>verifyFunctionBundle(changed.options));
  const wrongPin=await fixture();assert.throws(()=>verifyFunctionBundle({...wrongPin.options,bundleSha256:'0'.repeat(64)}));
});
test('plausible actual-builder labels, dummy vendor/bootstrap and extra invocation receipts never clear the function gate',async()=>{
  for(const kind of ['FUNCTION_FILE_INVENTORY','SIMULATED_FILTER_ONLY','ACTUAL_LOCAL_VERCEL_PYTHON_BUILDER_OUTPUT']) {
    const f=await fixture();f.report.kind=kind;f.report.architecture='x86_64';f.report.entrypoint='api/main.py';
    f.report.invocation={argv:['vercel','build'],cwd:f.root,exitCode:0,receiptSha256:sha('self-authored receipt'),builderPackageSha256:sha('self-authored builder')};
    const bootstrap='# fabricated bootstrap, not generated by a builder';await writeFile(path.join(f.bundle,'vc__handler__python.py'),bootstrap);
    f.report.records.push({path:'vc__handler__python.py',bytes:Buffer.byteLength(bootstrap),sha256:sha(bootstrap)});
    const diagnostic=verifyFunctionBundle(await f.save());assert.equal(diagnostic.functionBytes,null);assert.equal(diagnostic.hostedAcceptance,'UNRUN');
    const assessment=assessDelivery({metrics:{productBytes:1,productFiles:1,distBytes:1,manifestBytes:1,functionBytes:diagnostic.inventory.bytes},sourceUpload:{uncompressedBytes:1,files:1},staticFiles:1,buildDiskEstimateBytes:1,functionPackage:diagnostic,complete:true,platformReady:true});
    assert.equal(assessment.status,'BLOCKED_UNMEASURED_FUNCTION');assert.equal(assessment.functionMeasurement.actualBytes,null);assert.equal(assessment.platformReady,false);
  }
  const noVendor=await fixture();await unlink(path.join(noVendor.bundle,'_vendor/dependency.py'));noVendor.report.records=noVendor.report.records.filter(r=>!r.path.startsWith('_vendor/'));
  assert.equal(verifyFunctionBundle(await noVendor.save()).functionBytes,null);
});
test('shared project policy covers index/main and future API handlers without an exclusion escape or overlapping entries',async()=>{
  const config=JSON.parse(await readFile(path.join(REPO_ROOT,'vercel.json'),'utf8'));
  const policy=pythonFunctionPolicy(config);assert.equal(policy.maxDuration,300);
  for(const handler of ['api/index.py','api/main.py','api/nested/future.py','api/index','api/main'])assert(path.posix.matchesGlob(handler,'api/**'));
  for(const file of ['dist/index.html','dist/products/p/lod0.bin','public/products/p/lod0.gltf','public/decoders/basis/a.wasm','tools/product-curator/server.mjs','backend_tests/test_x.py','e2e/proof.ts','tests/check.ts'])assert(path.posix.matchesGlob(file,policy.excludeFiles),`Handler policy leaves development/static payload: ${file}`);
  for(const file of ['api/index.py','api/main.py','api/catalogue/providers/expansion/index.json','api/catalogue/providers/manifests/p.json','public/style-references/ref-01.jpg']) {
    assert(path.posix.matchesGlob(file,policy.includeFiles),`Missing required input: ${file}`);assert(!path.posix.matchesGlob(file,policy.excludeFiles),`Required input excluded: ${file}`);
  }
  assert.throws(()=>pythonFunctionPolicy({...config,functions:{'api/index.py':policy}}),/One shared/);
  assert.throws(()=>pythonFunctionPolicy({...config,functions:{...config.functions,'api/main.py':policy}}),/One shared/);
});
