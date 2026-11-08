// Selected originals must be self-contained GLB, never a filesystem/network loader.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
export async function selfContainedGlb(file) {
  const raw=await readFile(file);
  assert(raw.length>=20 && raw.length<=100_000_000 && raw.toString('ascii',0,4)==='glTF' && raw.readUInt32LE(4)===2 && raw.readUInt32LE(8)===raw.length,'Invalid bounded GLB');
  let cursor=12,document;
  while(cursor<raw.length) {
    assert(cursor+8<=raw.length);const length=raw.readUInt32LE(cursor),kind=raw.readUInt32LE(cursor+4);cursor+=8;
    assert(length%4===0 && cursor+length<=raw.length);
    if(kind===0x4e4f534a) {assert(!document && cursor===20,'GLB JSON must be the first unique chunk');document=JSON.parse(raw.toString('utf8',cursor,cursor+length));}
    else assert(kind===0x004e4942,'Unknown GLB chunk');
    cursor+=length;
  }
  assert(document?.asset?.version==='2.0');
  assert(document.buffers?.length===1 && !Object.hasOwn(document.buffers[0],'uri'),'External buffers rejected');
  assert((document.images??[]).every((i)=>!Object.hasOwn(i,'uri') && Number.isInteger(i.bufferView)),'External image paths/URLs rejected');
  assert((document.bufferViews??[]).every((v)=>v.buffer===0),'Unknown GLB buffer');
  return document;
}
