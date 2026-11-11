// Explicitly technical-only native/UI proof; never creates review decisions.
import assert from 'node:assert/strict';
import path from 'node:path';
import { cp, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';
import { createExpansionServer } from './expansion-server.mjs';
import { Expansion, args } from './expansion.mjs';
import { ownRoot, ownedPath, hashFile } from './safety.mjs';
import { durableFile } from './store.mjs';

const {command,options} = args(process.argv.slice(2)); assert.equal(command,'prove');
assert(process.env.FURNITUREOS_EVIDENCE_DIR,'External FURNITUREOS_EVIDENCE_DIR required');
const proof = await ownRoot(process.env.FURNITUREOS_EVIDENCE_DIR);
const app = await createExpansionServer({...options,port:0});
assert.equal(app.engine.state.evidenceKind,'technical-only','This proof must never start genuine agent/owner curation');
assert.equal(app.engine.report().counts.accepted,0);
const browser = await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const observations=[];
let fonts, mobile;
try {
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  await page.goto(app.origin);
  await page.waitForSelector('canvas');
  fonts=await page.evaluate(async()=>{await document.fonts.ready;await document.fonts.load('14px Manrope');await document.fonts.load('12px "Roboto Mono"');return [...document.fonts].map((f)=>({family:f.family,status:f.status}));});
  for(const family of ['Manrope','Roboto Mono']) assert(fonts.some((f)=>f.family.includes(family) && f.status==='loaded'),'Local review fonts must load');
  for(const c of app.engine.state.candidates.filter((c)=>c.preparation)) {
    const index=app.engine.state.candidates.findIndex((x)=>x.productId===c.productId);
    await page.getByLabel('Candidate').selectOption(String(index));
    for(const view of ['front','side','back','material','orientation','dimensions']) {
      const named=['material','orientation','dimensions'].includes(view)?'front':view;
      await page.getByRole('button',{name:`${named[0].toUpperCase()+named.slice(1)} view`,exact:true}).click();
      await page.waitForFunction(({productId,named})=>window.__curatorFrame?.url.includes(productId) && window.__curatorFrame.view===named && window.__curatorFrame.meshes>0 && window.__curatorFrame.textures>0 && window.__curatorFrame.loadedTextures===window.__curatorFrame.textures,{productId:c.productId,named},{timeout:60000});
      const frame=await page.evaluate(()=>window.__curatorFrame);
      const file=await ownedPath(proof,`${c.productId}-${view}.png`);await page.screenshot({path:file,fullPage:true});
      observations.push({productId:c.productId,view,evidenceFile:file,frame,pin:await hashFile(file)});
    }
  }
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(250);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Review viewport must not overflow horizontally');
  const mobileFile=await ownedPath(proof,'mobile-390.png');await page.screenshot({path:mobileFile,fullPage:true});mobile={viewport:{width:390,height:844},file:mobileFile,pin:await hashFile(mobileFile),scope:'controlled viewport, not a physical phone'};
  assert.equal((await page.request.get(`${app.origin}/api/expansion`,{headers:{Origin:'https://example.invalid'}})).status(),400);
  assert.equal((await page.request.get(`${app.origin}/public/products/anything`)).status(),404);
  assert.equal((await page.request.post(`${app.origin}/api/expansion`,{data:{}})).status(),400);
} finally { await browser.close();await app.close(); }
const engine=await Expansion.open(options);
try {
  const receipts=[];
  for(const observation of observations) receipts.push(await engine.observe(observation));
  assert.equal(engine.report().counts.accepted,0);
  await assert.rejects(engine.publication(),/Technical\/unfinished/);
  await durableFile(await ownedPath(proof,'TECHNICAL-ONLY.json'),{evidenceKind:'technical-only-NOT-genuine-review',origin:app.origin,report:engine.report(),observations,receipts,fonts,mobile,assertions:['actual Mesh draws and loaded materials in all inspected views','local fonts and 390px viewport without horizontal overflow','loopback origin and closed file inventory','no acceptance; cannot publish technical evidence']});
} finally {await engine.close();}
// Corrupt only a new external copy. The original native attempt remains intact.
const driftRoot=await ownedPath(proof,'acknowledged-drift-fixture');
await cp(options.stateDir,driftRoot,{recursive:true,errorOnExist:true,force:false});
const candidate=engine.state.candidates.find((c)=>c.preparation);
await writeFile(path.join(driftRoot,'attempts',candidate.preparation.id,'output','lod0.bin'),'CONTROLLED-CORRUPTION');
await assert.rejects(Expansion.open({...options,stateDir:driftRoot}));
await durableFile(await ownedPath(proof,'ACKNOWLEDGED-DRIFT-REJECTED.json'),{evidenceKind:'technical-only',fixture:driftRoot,originalPreserved:true,status:'CORRUPT_ACKNOWLEDGED_OUTPUT_REJECTED'});
console.log(`Technical-only Mesh/UI proof: ${proof}; zero accepted Products.`);
