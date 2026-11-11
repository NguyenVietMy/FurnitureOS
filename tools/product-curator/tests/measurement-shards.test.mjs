import test from 'node:test';
import assert from 'node:assert/strict';
import {verifyShards} from '../../../scripts/verify-measurement-shards.mjs';
import {sha} from '../../../scripts/lib/expansion-contract.mjs';
function fixture() {
  const productIds=Array.from({length:21},(_,i)=>`controlled-${String(i).padStart(2,'0')}`);
  const build={productIds,buildId:'CONTROLLED-test-only',catalogueVersion:'CONTROLLED-test-only'};
  const receipts=[0,1].map((page)=>({protocolVersion:'catalogue-shards-v1',buildId:build.buildId,catalogueVersion:build.catalogueVersion,allVisibleMs:1,shard:{page,pageCount:2,totalProducts:21,productIdsSha256:sha(JSON.stringify(productIds))},products:Object.fromEntries(productIds.slice(page*20,(page+1)*20).map((productId)=>[productId,{productId,error:null,initialLod:2,firstVisibleMs:1,refinements:[{lod:1},{lod:0}],lodState:Object.fromEntries([0,1,2].map((l)=>[l,{meshes:2,drawnMeshes:2,materials:1,textures:1,loadedTextures:1}]))}]))}));
  return {build,receipts};
}
test('complete deterministic pages include final partial page exactly once',()=>{const f=fixture();assert.equal(verifyShards(f.build,f.receipts).uniqueProducts,21);});
test('missing/duplicate/stale pages and incomplete drawn material state cannot claim union coverage',()=>{
  for(const change of [r=>r.pop(),r=>r[1]=r[0],r=>r[1].catalogueVersion='stale',r=>r[1].shard.productIdsSha256='0'.repeat(64),r=>Object.values(r[0].products)[0].lodState[0].loadedTextures=0,r=>Object.values(r[0].products)[0].lodState[0].drawnMeshes=1]) {const f=fixture();change(f.receipts);assert.throws(()=>verifyShards(f.build,f.receipts));}
});
