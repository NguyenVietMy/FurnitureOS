import { expect, test, type Page, type APIRequestContext } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

test.skip(process.env.FURNITUREOS_CONTROLLED_VARIANTS !== '1', 'Requires the explicit loopback controlled provider server.');
test.describe.configure({ mode:'default' });
const evidence=process.env.FURNITUREOS_EVIDENCE_DIR!;
const ownerToken=(owner:string)=>`controlled.${Buffer.from(JSON.stringify({sub:owner,is_anonymous:true})).toString('base64url')}.signature`;
const A={Authorization:'Bearer '+ownerToken('11111111-1111-1111-1111-111111111111')}, B={Authorization:'Bearer '+ownerToken('22222222-2222-2222-2222-222222222222')};
const mode=async(request:APIRequestContext,value:string)=>expect((await request.post('/__variants/mode',{data:{mode:value}})).ok()).toBe(true);
const release=async(request:APIRequestContext)=>expect((await request.post('/__variants/release')).ok()).toBe(true);
const ready=async(page:Page,label:string)=>{
  await expect(page.getByRole('button',{name:`Variant ${label} · Ready`,exact:true})).toBeEnabled();
};
const rendered=async(page:Page)=>{
  await page.waitForFunction(()=>window.__furnitureos?.usefulView.status==='complete');
  await page.waitForFunction(()=>Object.values(window.__furnitureos?.instances ?? {}).length>0
    && Object.values(window.__furnitureos?.instances ?? {}).every(p=>p.ready && p.actualFrameRendered && p.activeMeshCount>0));
  expect(await page.getByTestId('room-canvas').count()).toBe(1);
  const proof=await page.evaluate(()=>JSON.parse(JSON.stringify(window.__furnitureos)));
  expect(proof.errors).toEqual([]);
  expect(proof.usefulView.renderedPlacements).toBe(proof.usefulView.expectedPlacements);
  expect(proof.usefulView.materialsReady&&proof.usefulView.texturesReady).toBe(true);
  return proof;
};
const shot=async(page:Page,name:string)=>{
  mkdirSync(evidence,{recursive:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:join(evidence,`${name}.png`),fullPage:true});
  await page.screenshot({path:join(evidence,`${name}-viewport.png`)});
};
const inViewport=async(page:Page,label?:string)=>{
  // Geometry, not CSS visibility: selected feedback and the whole displayed
  // Room must share the actual viewport immediately after the interaction.
  const bounds=await page.evaluate(()=>{
    const stage=document.querySelector('.variant-workspace > .stage, .variant-workspace > .stage-placeholder')!.getBoundingClientRect();
    const controls=document.querySelector('.variant-controls')!.getBoundingClientRect();
    return {stage:{top:stage.top,bottom:stage.bottom,height:stage.height},controls:{top:controls.top,bottom:controls.bottom},height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth};
  });
  expect(bounds.stage.top).toBeGreaterThanOrEqual(-1);
  expect(bounds.stage.height).toBeGreaterThan(250);
  expect(bounds.controls.top).toBeGreaterThanOrEqual(bounds.stage.bottom-1);
  expect(bounds.controls.bottom).toBeLessThanOrEqual(bounds.height+1);
  expect(bounds.overflow).toBe(false);
  await test.info().attach('room-controls-viewport',{body:JSON.stringify(bounds),contentType:'application/json'});
  if(label)await expect(page.getByRole('button',{name:`Variant ${label} · Ready`,exact:true})).toHaveAttribute('aria-pressed','true');
  return bounds;
};
const startLive=async(page:Page,roomType:string)=>{
  await page.goto('/design/live');
  await page.getByRole('radio',{name:roomType==='bedroom'?'Bedroom':'Living room',exact:true}).check();
  await page.getByRole('radio',{name:'Soft neutrals and warm wood'}).check();
  await page.getByRole('button',{name:roomType==='bedroom'?'Generate bedroom':'Generate living room',exact:true}).click();
};

for(const roomType of ['bedroom','living-room']) test(`real ${roomType} stream exposes shell, usable mutable A, then distinct B/C`,async({page,request})=>{
  await page.setViewportSize({width:1440,height:1000});
  await page.addInitScript({content:readFileSync(resolve('scripts/variant-measurement-observer.mjs'),'utf8').replace('export function','function')+'\ninstallVariantObservation();'});
  await mode(request,'staged');
  await startLive(page,roomType);
  await expect(page.getByTestId('variant-shell')).toBeVisible();
  await inViewport(page);
  await shot(page,`${roomType}-shell`);
  // Hold B next, allowing A to be used independently of ongoing generation.
  await request.post('/__variants/release-a');
  await ready(page,'A');await rendered(page);
  await inViewport(page,'A');
  await expect(page.getByRole('button',{name:'Variant B · Pending'})).toBeDisabled();
  const swap=page.getByTestId('swap-controls');
  await expect(swap).toHaveAttribute('data-version','1');
  await page.getByRole('button',{name:'Check compatible Products',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Compatible Product'})).toBeVisible();
  const replacement=await page.getByRole('combobox',{name:'Compatible Product'}).inputValue();
  await page.getByRole('button',{name:'Swap Product',exact:true}).click();
  await expect(swap).toHaveAttribute('data-version','2');
  await expect.poll(()=>page.evaluate(()=>window.__furnitureos?.instances['anchor-bed']?.productId ?? window.__furnitureos?.instances['anchor-sofa']?.productId)).toBe(replacement);
  const changed=await rendered(page);
  await shot(page,`${roomType}-A-usable-before-B`);
  await release(request);
  await ready(page,'B');await ready(page,'C');
  await page.waitForFunction(()=>(window as any).__variantWire?.done);
  const observed=await page.evaluate(()=>(window as any).__variantWire);
  expect(observed.error).toBeNull();expect(observed.outcome.available).toEqual(['A','B','C']);
  expect(observed.outcome.usage.known).toBe(false);
  await expect(page.getByRole('button',{name:'Variant A · Ready',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(swap).toHaveAttribute('data-version','2');
  const signatures=[];
  for(const label of ['B','C','A']){
    await page.getByRole('button',{name:`Variant ${label} · Ready`,exact:true}).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button',{name:`Variant ${label} · Ready`,exact:true})).toBeFocused();
    await inViewport(page,label);
    const proof=await rendered(page);signatures.push(proof.instances);
    await expect(swap).toHaveAttribute('data-version',label==='A'?'2':'1');
  }
  const restored=await rendered(page);
  expect(Object.fromEntries(Object.entries(restored.instances).map(([id,p]:any)=>[id,[p.productId,p.publishedPlacement]]))).toEqual(Object.fromEntries(Object.entries(changed.instances).map(([id,p]:any)=>[id,[p.productId,p.publishedPlacement]])));
  expect(JSON.stringify(signatures[0])).not.toEqual(JSON.stringify(signatures[1]));
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Variant B · Ready',exact:true}).click();await inViewport(page,'B');
  await page.getByRole('button',{name:'Variant A · Ready',exact:true}).click();await rendered(page);await inViewport(page,'A');
  await shot(page,`${roomType}-mobile-variants`);
  await mode(request,'staged');
  await page.getByRole('button',{name:roomType==='bedroom'?'Generate bedroom':'Generate living room',exact:true}).click();
  await expect(page.getByTestId('variant-shell')).toBeVisible();await inViewport(page);
  await request.post('/__variants/release-a');await ready(page,'A');await rendered(page);await inViewport(page,'A');
  await release(request);await ready(page,'C');
});

test('server-accepted Swap and Nudge reconcile A after A → B → A while each response is held',async({page,request})=>{
  await mode(request,'hold');await startLive(page,'bedroom');await ready(page,'A');await release(request);await ready(page,'C');await rendered(page);
  for(const operation of ['swap','nudge']){
    let releaseResponse!:()=>void,accepted!:(value:any)=>void;
    const gate=new Promise<void>(resolve=>{releaseResponse=resolve;});
    const committed=new Promise<any>(resolve=>{accepted=resolve;});
    const endpoint=operation==='swap'?'**/api/swaps':'**/api/nudges';
    await page.route(endpoint,async route=>{
      const response=await route.fetch();
      const result=await response.json();accepted(result);
      await gate;await route.fulfill({response});
    });
    const before=Number(await page.getByTestId('swap-controls').getAttribute('data-version'));
    if(operation==='swap'){
      await page.getByRole('button',{name:'Check compatible Products',exact:true}).click();
      await expect(page.getByRole('combobox',{name:'Compatible Product'})).toBeVisible();
      await page.getByRole('button',{name:'Swap Product',exact:true}).click();
    }else{
      await page.getByRole('combobox',{name:'Placement to Nudge'}).selectOption('anchor-bed');
      await page.getByRole('button',{name:/Prepare Nudge|Retry Nudge/}).click();
      await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state','ready');
      await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();
      const canvas=(await page.getByTestId('room-canvas').locator('canvas').boundingBox())!;
      const points=await page.evaluate(()=>window.__furnitureos!.instances['anchor-bed']!.screenPoints ?? []);
      let grabbed=false;
      for(const [x,y] of points){
        const px=canvas.x+(x+1)*canvas.width/2,py=canvas.y+(1-y)*canvas.height/2;
        await page.mouse.move(px,py);await page.mouse.down();
        const status=await page.getByTestId('nudge-controls').getAttribute('data-state');
        if(status==='dragging'||status==='clamped'){await page.mouse.move(px+35,py+15,{steps:8});grabbed=true;break;}
        await page.mouse.up();
      }
      expect(grabbed).toBe(true);await page.mouse.up();
    }
    const result=await committed;expect(result.status).toBe('accepted');expect(result.version).toBe(before+1);
    await page.getByRole('button',{name:'Variant B · Ready',exact:true}).click();await rendered(page);
    await expect(page.getByTestId('swap-controls')).toHaveAttribute('data-version','1');
    await page.getByRole('button',{name:'Variant A · Ready',exact:true}).click();await rendered(page);
    releaseResponse();
    await expect(page.getByTestId('swap-controls')).toHaveAttribute('data-version',String(before+1));
    const restored=await rendered(page);
    for(const placement of result.design.placements){
      expect(restored.instances[placement.instanceId].productId).toBe(placement.productId);
      expect(restored.instances[placement.instanceId].publishedPlacement).toMatchObject({position:placement.position,yaw:placement.yaw});
      const intent=result.design.intents.find((value:any)=>value.id===placement.instanceId);
      expect(restored.instances[placement.instanceId].publishedPlacement.wallId).toBe(intent?.wallId ?? null);
    }
    await page.unroute(endpoint);
  }
});

test('real stream later failure and explicit Stop retain A; supersession and navigation suppress late output',async({page,request})=>{
  await mode(request,'partial');await startLive(page,'bedroom');await ready(page,'A');await rendered(page);
  await expect(page.getByRole('region',{name:'Design Variants'})).toContainText('Controlled later failure');
  await expect(page.getByRole('button',{name:'Variant B · Unavailable'})).toBeDisabled();
  await mode(request,'hold');
  await page.getByRole('button',{name:'Generate bedroom',exact:true}).click();await ready(page,'A');await rendered(page);
  await page.getByRole('button',{name:'Stop generation',exact:true}).click();await release(request);
  await expect(page.getByRole('button',{name:'Variant B · Unavailable'})).toBeDisabled();
  await rendered(page);
  await mode(request,'hold');await page.getByRole('button',{name:'Generate bedroom',exact:true}).click();await ready(page,'A');
  await page.getByRole('radio',{name:'Living room',exact:true}).check();
  await expect(page.getByTestId('live-idle')).toBeVisible();await release(request);
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await mode(request,'hold');await startLive(page,'bedroom');await ready(page,'A');
  await page.getByRole('link',{name:'Fixture preview',exact:false}).click();await release(request);
  await expect(page.getByTestId('live-bedroom')).toHaveCount(0);
});

async function createCapture(request:APIRequestContext,roomType:string,topology:string){
  const post=async(path:string,data:any)=>{const r=await request.post(path,{data,headers:A});expect(r.ok(),await r.text()).toBe(true);return r.json();};
  let c=await post('/api/captures',{consent:true});
  const patch=async(draft:any)=>{const r=await request.patch(`/api/captures/${c.id}/draft`,{data:{expectedRevision:c.revision,draft},headers:A});expect(r.ok()).toBe(true);c=await r.json();};
  await patch({...c.draft,roomType,topology});
  const walls=topology==='rectangle'?['wall-north','wall-east','wall-south','wall-west']:['wall-north','wall-notch-vertical','wall-notch-horizontal','wall-east','wall-south','wall-west'];
  for(let i=0;i<walls.length;i++){
    const bytes=execFileSync(resolve('.venv/Scripts/python.exe'),['-c','import sys;from backend_tests.test_captures import png;sys.stdout.buffer.write(png(int(sys.argv[1])))',String(i)]);
    c=await post(`/api/captures/${c.id}/photos`,{expectedRevision:c.revision,primaryWallId:walls[i],declaredBytes:bytes.length});
    const r=await request.post(`/api/captures/${c.id}/photos/${c.photos.at(-1).id}/content?expectedRevision=${c.revision}`,{data:bytes,headers:{...A,'Content-Type':'image/png'}});expect(r.ok()).toBe(true);c=await r.json();
  }
  const draft={...c.draft,widthM:8,depthM:8,heightM:2.7,...(topology==='L-shaped'?{notchWidthM:2,notchDepthM:2}:{}),dimensionsConfirmed:true,wallReviews:walls,furnitureAcknowledged:true};
  await patch(draft);await patch(draft);
  const confirmed=await post(`/api/captures/${c.id}/confirm`,{expectedRevision:c.revision});expect(confirmed.status).toBe('confirmed');return confirmed.capture;
}
async function restore(page:Page,c:any){
  const owner='11111111-1111-1111-1111-111111111111';
  const session={access_token:A.Authorization.slice(7),token_type:'bearer',expires_in:3600,expires_at:Math.floor(Date.now()/1000)+3600,refresh_token:'CONTROLLED',user:{id:owner,aud:'authenticated',role:'authenticated',is_anonymous:true,created_at:new Date().toISOString()}};
  await page.addInitScript(({owner,session,id})=>{localStorage.setItem('sb-capture-test-auth-token',JSON.stringify(session));localStorage.setItem(`furnitureos.capture.${owner}`,id);},{owner,session,id:c.id});
  await page.route('https://capture-test.invalid/auth/v1/**',route=>route.fulfill({json:route.request().url().endsWith('/user')?session.user:session}));
  await page.goto('/capture');
  await page.getByRole('radio',{name:'Soft neutrals and warm wood'}).check();
}
for(const roomType of ['bedroom','living-room'])for(const topology of ['rectangle','L-shaped'])test(`real private ${roomType} ${topology} stream binds every Variant and denies outsiders/stale callbacks`,async({page,request})=>{
  await mode(request,'hold');const c=await createCapture(request,roomType,topology);await restore(page,c);
  const path=`/api/captures/${c.id}/variants`,body={expectedRevision:c.revision,referenceId:'ref-01'};
  expect((await request.post(path,{data:body,headers:B})).status()).toBe(404);
  expect((await request.post(path,{data:{...body,expectedRevision:c.revision-1},headers:A})).status()).toBe(409);
  await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();await ready(page,'A');await rendered(page);
  await inViewport(page,'A');
  if(roomType==='living-room'){
    await expect(page.getByRole('region',{name:'Seating Zones',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'Seating Zones',exact:true})).toContainText('m wide');
  }
  await release(request);await ready(page,'B');await ready(page,'C');
  const sessions:string[]=[],designs:string[]=[];
  for(const label of ['B','C','A']){
    await page.getByRole('button',{name:`Variant ${label} · Ready`,exact:true}).click();await rendered(page);
    await expect(page.getByTestId('swap-controls')).toHaveAttribute('data-version','1');
    const sid=(await page.getByTestId('swap-controls').getAttribute('data-session-id'))!;
    sessions.push(sid);
    expect((await (await request.get(`/api/swaps/${sid}`,{headers:B})).json()).status).toBe('unknown-session');
    const current=await (await request.get(`/api/swaps/${sid}`,{headers:A})).json();
    expect(current.status).toBe('current');expect(current.design.room).toEqual(c.room);
    designs.push(JSON.stringify(current.design.placements.map((p:any)=>[p.productId,p.position,p.yaw]).sort()));
  }
  expect(new Set(sessions).size).toBe(3);expect(new Set(designs).size).toBe(3);
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Variant B · Ready',exact:true}).click();await inViewport(page,'B');
  await page.getByRole('button',{name:'Variant A · Ready',exact:true}).click();await rendered(page);await inViewport(page,'A');
  await shot(page,`capture-${roomType}-${topology}`);
  if(roomType==='bedroom'&&topology==='rectangle'){
    await mode(request,'hold');await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();await ready(page,'A');
    await page.getByRole('button',{name:'Stop generation',exact:true}).click();await release(request);
    await expect.poll(async()=> (await (await request.get('/__variants/state')).json()).leases).toBe(0);
    await ready(page,'A');await rendered(page);
    await expect(page.getByRole('button',{name:'Variant B · Unavailable'})).toBeDisabled();
  }
  await mode(request,'hold');await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();await ready(page,'A');
  await request.post(`/__variants/invalidate/${c.id}`);await release(request);
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect(page.getByRole('region',{name:'Design Variants'})).toContainText(/access changed|expired|interrupted/);
  await expect.poll(async()=> (await (await request.get('/__variants/state')).json()).leases).toBe(0);
});
