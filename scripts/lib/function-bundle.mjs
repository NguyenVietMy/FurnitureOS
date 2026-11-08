// Verify local file bytes and input parity, never invocation or dependency closure.
import assert from 'node:assert/strict';
import {readFileSync,readdirSync,lstatSync,existsSync} from 'node:fs';
import path from 'node:path';
import {sha,pin,noLinkedPath} from './expansion-contract.mjs';

function files(root,relative='') {
  return readdirSync(path.join(root,relative)).flatMap(name=>{
    const rel=relative?`${relative}/${name}`:name;
    const full=noLinkedPath(path.join(root,rel));
    return lstatSync(full).isDirectory()?files(root,rel):[rel];
  });
}
// One documented shared pattern covers every emitted API handler, with no
// overlapping per-handler policy or assumed suppression by pyproject discovery.
export function pythonFunctionPolicy(config) {
  assert.deepEqual(Object.keys(config.functions??{}),['api/**'],'One shared api/** function policy is required');
  const policy=config.functions['api/**'];
  assert(policy && typeof policy.includeFiles==='string' && policy.includeFiles.length>0);
  assert(typeof policy.excludeFiles==='string' && policy.excludeFiles.length>0);
  return policy;
}
export function verifyFunctionBundle({bundlePath,bundleSha256,root}) {
  const raw=readFileSync(noLinkedPath(bundlePath));assert.equal(sha(raw),pin(bundleSha256));
  const b=JSON.parse(raw),dir=path.join(path.dirname(path.resolve(bundlePath)),'bundle');
  assert.equal(b.schemaVersion,1);assert(['FUNCTION_FILE_INVENTORY','SIMULATED_FILTER_ONLY','ACTUAL_LOCAL_VERCEL_PYTHON_BUILDER_OUTPUT'].includes(b.kind));
  assert.equal(b.builder.name,'@vercel/python');assert(/^\d+\.\d+\.\d+$/.test(b.builder.version));
  assert(/^python3\.\d+$/.test(b.runtime));
  const config=JSON.parse(readFileSync(path.join(root,'vercel.json'),'utf8'));
  pythonFunctionPolicy(config);
  assert.deepEqual(b.config,config,'Package configuration changed');
  assert(Array.isArray(b.records) && b.records.length>0 && b.records.length<=25000);
  const names=b.records.map(r=>r.path);
  assert.equal(new Set(names).size,names.length,'Duplicate package path');
  assert.deepEqual([...names].sort(),files(dir).sort(),'Package inventory changed');
  let total=0;
  for(const r of b.records) {
    assert(typeof r.path==='string' && !r.path.includes('\\') && !r.path.includes(':') && r.path.split('/').every(p=>p && p!=='.' && p!=='..'),'Unsafe package path');
    assert(!/^(?:dist|tools|backend_tests|e2e|tests|public\/(?:products|decoders))\//.test(r.path),'Static or development payload in Python bundle');
    const data=readFileSync(noLinkedPath(path.join(dir,r.path)));
    assert.equal(data.length,r.bytes);assert.equal(sha(data),pin(r.sha256));total+=data.length;
    const current=path.join(root,r.path);
    if(existsSync(current) && lstatSync(noLinkedPath(current)).isFile()) {
      assert.equal(sha(readFileSync(current)),r.sha256,`Packaged project input changed: ${r.path}`);
    }
  }
  const byName=new Map(b.records.map(r=>[r.path,r]));
  if(b.entrypoint!==undefined) {
    assert(typeof b.entrypoint==='string' && b.entrypoint.startsWith('api/') && b.entrypoint.endsWith('.py') && !b.entrypoint.split('/').includes('..'));
    assert(byName.has(b.entrypoint),'Declared handler missing from inventory');
  }
  // Check every current authority input, including generated pinned manifests.
  for(const base of ['api','public/style-references']) for(const p of files(path.join(root,base))) {
    if(p.split('/').includes('__pycache__') || p.endsWith('.pyc'))continue;
    const name=`${base}/${p}`,r=byName.get(name);assert(r,`Missing runtime input: ${name}`);
    const data=readFileSync(path.join(root,name));assert.equal(data.length,r.bytes);assert.equal(sha(data),r.sha256,`Runtime input changed: ${name}`);
  }
  // A vendor filename, bootstrap, version or caller-authored invocation receipt
  // cannot establish which builder ran or whether all runtime dependencies exist.
  for(const name of ['pyproject.toml','uv.lock']) {
    const r=byName.get(name);assert(r,`Missing runtime dependency declaration: ${name}`);
    assert.equal(sha(readFileSync(path.join(root,name))),r.sha256,`Runtime dependency declaration changed: ${name}`);
  }
  assert.equal(b.totalBytes,total);assert.equal(b.files,names.length);
  return {status:'DIAGNOSTIC_LOCAL_FILE_INVENTORY',bundleSha256,
    inventory:{files:names.length,bytes:total},
    asserted:{kind:b.kind,builder:b.builder,runtime:b.runtime,architecture:b.architecture,entrypoint:b.entrypoint??'UNKNOWN'},
    verified:{fileUnionAndHashes:true,currentRuntimeInputsMatch:true,configurationMatches:true},
    builderInvocation:'UNRUN',dependencyClosure:'UNKNOWN',functionBytes:null,
    platformReady:false,hostedAcceptance:'UNRUN',
    evidenceAuthority:'LOCAL_FILES_ONLY_PROVENANCE_UNESTABLISHED',
    scope:'Only the listed local bytes and input parity are established. Builder invocation, dependencies, bootstrap and bytecode completeness are not established; this inventory cannot clear a function-size gate.'};
}
