import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdir,readFile} from 'node:fs/promises';
import path from 'node:path';
import {Document,NodeIO} from '@gltf-transform/core';
import {unpackSource} from '../../../scripts/build-product-assets.mjs';
import {evidenceDir} from './helpers.mjs';

test('source normalization writes and remeasures micrometre offsets instead of silently omitting the transform',async()=>{
  const root=await evidenceDir('actual-source-normalization-serialization-regression');
  for(const offset of [0.000003,0.000009,-0.000003,-0.000009,0,0.001]) {
    const dir=path.join(root,String(offset));await mkdir(dir);const doc=new Document(),buffer=doc.createBuffer();
    const positions=doc.createAccessor().setType('VEC3').setArray(new Float32Array([-1,0,-.47+offset,1,1,.47+offset,-1,1,.47+offset])).setBuffer(buffer);
    const indices=doc.createAccessor().setType('SCALAR').setArray(new Uint16Array([0,1,2])).setBuffer(buffer);
    const primitive=doc.createPrimitive().setAttribute('POSITION',positions).setIndices(indices);
    const mesh=doc.createMesh().addPrimitive(primitive),scene=doc.createScene().addChild(doc.createNode().setMesh(mesh));doc.getRoot().setDefaultScene(scene);
    const file=path.join(dir,'controlled.glb');await new NodeIO().write(file,doc);
    const work=path.join(dir,'work');await mkdir(work);const result=await unpackSource(file,work);
    for(const field of ['min','max'])for(let axis=0;axis<3;axis++)assert(Math.abs(result.normalizedMeasure[field][axis]-result.rawMeasure[field][axis]-result.translation[axis])<=.000001,`Actual serialized ${offset} offset not applied on ${field}[${axis}]`);
    assert.deepEqual(result.normalizedMeasure.size,result.rawMeasure.size);
    assert.equal(result.normalizedMeasure.triangles,result.rawMeasure.triangles);
    const gltf=JSON.parse(await readFile(result.unpacked,'utf8'));assert.equal(gltf.scenes.length,1);
  }
});
