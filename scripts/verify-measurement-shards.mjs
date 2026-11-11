import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { sha } from './lib/expansion-contract.mjs';
export function verifyShards(build,receipts) {
  const expected=[...build.productIds].sort(), pages=Math.ceil(expected.length/20), seen=[];
  assert.equal(new Set(expected).size,expected.length); assert.equal(receipts.length,pages,'Every page required exactly once');
  assert.equal(new Set(receipts.map((r)=>r.shard?.page)).size,pages,'Duplicate page receipt');
  for(const r of receipts) {
    assert.equal(r.protocolVersion,'catalogue-shards-v1');
    assert.equal(r.buildId,build.buildId);assert.equal(r.catalogueVersion,build.catalogueVersion);
    assert(r.shard && Number.isInteger(r.shard.page) && r.shard.page>=0 && r.shard.page<pages);
    assert.equal(r.shard.pageCount,pages);assert.equal(r.shard.totalProducts,expected.length);assert.equal(r.shard.productIdsSha256,sha(JSON.stringify(expected)));
    const ids=Object.keys(r.products).sort();assert.deepEqual(ids,expected.slice(r.shard.page*20,(r.shard.page+1)*20));
    assert(r.allVisibleMs !== null);
    for(const p of Object.values(r.products)) {
      assert(p.error === null && p.initialLod === 2 && p.firstVisibleMs !== null);
      assert([0,1].every((l)=>p.refinements.some((e)=>e.lod===l)));
      for(const lod of [0,1,2]) {const s=p.lodState?.[lod];assert(s && s.meshes>0 && s.drawnMeshes===s.meshes && s.materials>0 && s.textures>0 && s.loadedTextures===s.textures,`Incomplete actual Mesh/material state ${p.productId} LOD${lod}`);}
    }
    seen.push(...ids);
  }
  assert.deepEqual(seen.sort(),expected);
  return {catalogueVersion:build.catalogueVersion,buildId:build.buildId,pages,uniqueProducts:expected.length,status:'COMPLETE_CONTROLLED_MESH_COVERAGE',physicalPhoneStatus:'WAIVED_NOT_PASSED'};
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const [build,...runs]=process.argv.slice(2);assert(build && runs.length);console.log(JSON.stringify(verifyShards(JSON.parse(readFileSync(build)),runs.map((f)=>JSON.parse(readFileSync(f)))),null,2));
}
