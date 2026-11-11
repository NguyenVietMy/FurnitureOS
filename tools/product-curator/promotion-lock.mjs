// Stable ignored lock inode; process receipts and recovered bytes stay external.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomUUID,createHash} from 'node:crypto';
import {mkdir,readFile,readdir,open,unlink,lstat} from 'node:fs/promises';
import path from 'node:path';
import {createInterface} from 'node:readline';
import {REPO_ROOT} from '../../scripts/lib/paths.mjs';
import {noLinks,ownedPath,hashFile} from './safety.mjs';
import {durableFile} from './store.mjs';

const uuid='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const transient=new RegExp(`^(?:\\.index-${uuid}\\.pending|stale-lock-${uuid}\\.json)$`);
const sha=(b)=>createHash('sha256').update(b).digest('hex');
async function retain(transaction,name,bytes) {
  const dir=await ownedPath(transaction,'recovered-transients');await mkdir(dir,{recursive:true});
  const file=await ownedPath(transaction,'recovered-transients',`${randomUUID()}-${name}`),handle=await open(file,'wx');
  try{await handle.writeFile(bytes);await handle.sync();}finally{await handle.close();}
  assert.deepEqual(await hashFile(file),{bytes:bytes.length,sha256:sha(bytes)});return {file,bytes:bytes.length,sha256:sha(bytes)};
}
export async function promotionWriter(directory,transaction) {
  const lockPath=await noLinks(path.join(directory,'.promotion.lock'));
  const python=path.join(REPO_ROOT,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
  const argv=[path.join(REPO_ROOT,'tools/product-curator/promotion-lock.py'),lockPath];
  const child=spawn(python,argv,{cwd:REPO_ROOT,windowsHide:true,stdio:['pipe','pipe','pipe']});
  // A helper exit rejects the outstanding protocol read; avoid an unhandled
  // pipe error masking that retained failure on Windows.
  child.stdin.on('error',()=>{});
  let stderr='';child.stderr.on('data',b=>{stderr=(stderr+b).slice(-4096);});
  const lines=createInterface({input:child.stdout});
  const exited=new Promise(resolve=>{child.once('exit',code=>resolve(code));child.once('error',()=>resolve(-1));});
  const next=()=>new Promise((resolve,reject)=>{
    const clear=()=>{lines.off('line',line);child.off('exit',end);child.off('error',error);};
    const line=value=>{clear();try{resolve(JSON.parse(value));}catch(e){reject(e);}};
    const end=code=>{clear();reject(new Error(code===42?'Concurrent promotion writer is active':`Promotion lock helper exit ${code}: ${stderr}`));};
    const error=e=>{clear();reject(e);};lines.once('line',line);child.once('exit',end);child.once('error',error);
  });
  const close=async()=>{child.stdin.end();const code=await exited;lines.close();assert.equal(code,0,`Promotion lock helper exit ${code}: ${stderr}`);};
  try {
    const ready=await next();assert.equal(ready.status,'LOCKED');const raw=Buffer.from(ready.rawBase64,'base64');let legacy=null;
    if(raw.length && !raw.equals(Buffer.from(' '))) {
      const owner=JSON.parse(raw);assert.deepEqual(Object.keys(owner).sort(),['id','pid']);assert(new RegExp(`^${uuid}$`).test(owner.id) && Number.isInteger(owner.pid) && owner.pid>0,'Unknown legacy lock; preserve');
      try{process.kill(owner.pid,0);throw new Error('Concurrent promotion legacy writer is active');}catch(e){if(e.code!=='ESRCH')throw e;}
      legacy=await retain(transaction,'legacy-promotion-lock.json',raw);
    }
    const held=next();child.stdin.write(JSON.stringify({normalizeSha256:sha(raw)})+'\n');assert.equal((await held).status,'HELD');
    const recovered=[];
    for(const name of await readdir(directory)) if(transient.test(name)) {
      const source=await noLinks(path.join(directory,name)),info=await lstat(source);assert(info.isFile() && info.size<=20_000_000,'Unknown oversized promotion transient; preserve');
      const bytes=await readFile(source);
      if(name.startsWith('stale-lock-')) {const owner=JSON.parse(bytes);assert.deepEqual(Object.keys(owner).sort(),['id','pid']);assert(new RegExp(`^${uuid}$`).test(owner.id) && Number.isInteger(owner.pid) && owner.pid>0,'Unknown legacy transient; preserve');}
      const retained=await retain(transaction,name,bytes);
      assert.deepEqual(await hashFile(source),{bytes:retained.bytes,sha256:retained.sha256},'Promotion transient changed');
      await unlink(source);recovered.push(retained);
    }
    await durableFile(path.join(transaction,'lock-acquired.json'),{protocol:'os-byte-lock-v1',pid:process.pid,helperPid:child.pid,argv:[python,...argv],cwd:REPO_ROOT,at:new Date().toISOString(),legacy,recovered});
    const release=async()=>{await close();await durableFile(path.join(transaction,'lock-released.json'),{at:new Date().toISOString()});};
    release.assertHeld=()=>assert(child.exitCode===null && child.signalCode===null && child.stdin.writable,'Promotion OS lock lease ended');
    return release;
  }catch(error){child.stdin.end();await exited;lines.close();throw error;}
}
