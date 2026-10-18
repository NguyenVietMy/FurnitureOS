import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, type Page, type APIRequestContext } from '@playwright/test';
import type { CaptureSemanticProposal, SemanticOpening } from '../src/shared/api/types';

// Explicit OFFLINE auth/storage/provider transport. The actual Python rectangle,
// calibration authority and HTTP arrangement solver run; this is not live RLS proof.
const root=fileURLToPath(new URL('..',import.meta.url));
export const evidence=process.env.FURNITUREOS_EVIDENCE_DIR??join(root,'test-results','capture');
mkdirSync(evidence,{recursive:true});
const owner='11111111-1111-1111-1111-111111111111',id='33333333-3333-3333-3333-333333333333';
const walls=['wall-north','wall-east','wall-south','wall-west'] as const;
function authority(action:string,data:unknown) {
  const code=action==='confirm'
    ? 'import json,sys; from api.capture_models import CaptureView; from api.capture_room import validate_capture_rectangle,room_hash; c=CaptureView.model_validate(json.load(sys.stdin)); r,i=validate_capture_rectangle(c); print(json.dumps({"room":r.model_dump(mode="json") if r else None,"issues":[x.model_dump() for x in i],"hash":room_hash(r) if r else None}))'
    : action==='normalize' ? 'import json,sys; from api.capture_transitions import normalize_draft; d=json.load(sys.stdin); print(json.dumps(normalize_draft(d["before"],d["after"])))'
    : 'import json,sys; from api.capture_models import ReferenceRequest; from api.capture_reference import calibrate; print(calibrate(ReferenceRequest.model_validate(json.load(sys.stdin)),1280,960).model_dump_json())';
  return JSON.parse(execFileSync(join(root,'.venv','Scripts','python.exe'),['-c',code],{cwd:root,input:JSON.stringify(data),encoding:'utf8'}));
}
type IdentityOptions={createdFlag?:boolean|null;restoredFlag?:boolean|null;create?:boolean;analysisProposals?:ReadonlyArray<CaptureSemanticProposal>};
export async function controlled(page:Page,request:APIRequestContext,options:IdentityOptions={}) {
  const blank={roomType:'',topology:'',widthM:null,depthM:null,heightM:null,dimensionsConfirmed:false,wallReviews:[],openings:[],furnitureAcknowledged:false,dimensionEvidence:[]};
  let capture:any={id,revision:1,state:'draft',createdAt:new Date().toISOString(),expiresAt:new Date(Date.now()+86400000).toISOString(),draft:blank,photos:[],confirmedRevision:null,roomHash:null,room:null,cleanupStatus:'none',calibrations:[]};
  const photos=new Map<string,Buffer>();let generations=0,finished=0,holdGeneration:Promise<void>|null=null,deleted=false,privateRequests=0;
  const authRequests:Array<{path:string;method:string}>=[];
  const profile=(flag:boolean|null)=>({id:owner,aud:'authenticated',role:'authenticated',...(flag===null?{}:{is_anonymous:flag}),user_metadata:{is_anonymous:true},created_at:new Date().toISOString()});
  const session=(flag:boolean|null)=>({access_token:'controlled-owner-jwt',token_type:'bearer',expires_in:3600,expires_at:Math.floor(Date.now()/1000)+3600,refresh_token:'controlled-refresh',user:profile(flag)});
  if('restoredFlag' in options)await page.addInitScript(({session,owner,id})=>{
    localStorage.setItem('sb-capture-test-auth-token',JSON.stringify(session));
    localStorage.setItem(`furnitureos.capture.${owner}`,id);
  },{session:session(options.restoredFlag??null),owner,id});
  const config=await (await request.get('/api/live-bedroom/config')).json();
  await page.route('https://capture-test.invalid/auth/v1/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname;authRequests.push({path,method:req.method()});
    const flag='restoredFlag' in options?options.restoredFlag??null:options.createdFlag===undefined?true:options.createdFlag;
    return route.fulfill({json:path.endsWith('/user')?profile(flag):session(flag)});
  });
  await page.route('**/api/captures/config',route=>route.fulfill({json:{storageReady:true,analysisAvailable:true,generationAvailable:true,retentionHours:24,maxPhotos:8,maxInputBytes:4000000,detail:'Explicit controlled OFFLINE transport',authUrl:'https://capture-test.invalid',publishableKey:'controlled-public'}}));
  await page.route('**/api/captures/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname,method=req.method();
    if(path==='/api/captures/config')return route.fallback();
    privateRequests++;
    expect(req.headers().authorization).toBe('Bearer controlled-owner-jwt');
    const body=req.postDataJSON?.bind(req);
    if(path.endsWith('/deletion'))return capture.state==='deleting'&&!deleted
      ?route.fulfill({json:{id,state:'deleting',inaccessible:true,cleanupStatus:capture.cleanupStatus}})
      :route.fulfill({status:404,json:{detail:'This Capture is unavailable.'}});
    if(path.endsWith('/content')) {
      const pid=path.split('/').at(-2)!;
      if(method==='GET')return route.fulfill({body:photos.get(pid)!,contentType:'image/jpeg',headers:{'Cache-Control':'no-store'}});
      const canonical=req.postDataBuffer()!,digest=createHash('sha256').update(canonical).digest('hex');
      expect(capture.photos.some((p:any)=>p.state==='accepted'&&p.sha256===digest)).toBe(false);
      photos.set(pid,canonical);const photo=capture.photos.find((p:any)=>p.id===pid);
      Object.assign(photo,{state:'accepted',inputBytes:req.postDataBuffer()!.length,canonicalBytes:req.postDataBuffer()!.length,sha256:digest,widthPx:1280,heightPx:960});
      return route.fulfill({json:capture});
    }
    if(path.endsWith('/photos')&&method==='POST') {
      const b=body();expect(b.expectedRevision).toBe(capture.revision);capture.revision++;
      capture.photos.push({id:`44444444-4444-4444-4444-${String(capture.photos.length+1).padStart(12,'0')}`,primaryWallId:b.primaryWallId,observedWallIds:[],state:'reserved',declaredBytes:b.declaredBytes,inputBytes:0,canonicalBytes:0,sha256:null,widthPx:0,heightPx:0,analysisStatus:'unknown',analysisAttempts:0,semantics:null});
    } else if(/\/photos\/[^/]+$/.test(path)&&method==='PATCH') {
      const b=body(),photo=capture.photos.find((p:any)=>p.id===path.split('/').at(-1));
      Object.assign(photo,{primaryWallId:b.primaryWallId,observedWallIds:b.observedWallIds,semantics:null,analysisStatus:'unknown'});
      Object.assign(capture,{revision:capture.revision+1,state:'draft',room:null,roomHash:null,confirmedRevision:null,
        calibrations:[],draft:{...capture.draft,dimensionsConfirmed:false,wallReviews:[],dimensionEvidence:[]}});
    } else if(/\/photos\/[^/]+$/.test(path)&&method==='DELETE') {
      const pid=path.split('/').at(-1);capture.photos=capture.photos.filter((p:any)=>p.id!==pid);photos.delete(pid!);
      Object.assign(capture,{revision:capture.revision+1,state:'draft',room:null,roomHash:null,confirmedRevision:null,
        calibrations:[],draft:{...capture.draft,dimensionsConfirmed:false,wallReviews:[],dimensionEvidence:[]}});
    } else if(path.endsWith('/analyze')) {
      expect(body().expectedRevision).toBe(capture.revision);
      const photo=capture.photos.find((p:any)=>p.id===path.split('/').at(-2));expect(photo.analysisAttempts).toBeLessThan(2);
      const prior=photo.semantics?.openings??[];
      const proposal:CaptureSemanticProposal=options.analysisProposals?.[photo.analysisAttempts]??{openings:[{id:'uncertain-proposal',wallId:'wall-north',kind:'door',location:'near-start',visibility:'partial',direction:'unknown',angle:'unknown',hingeSide:'unknown',description:'Controlled uncertain door proposal'}],detectedFurniture:'present',observation:'partial'};
      // Mirror the separately SQL/HTTP-proved transaction, never overwrite corrections.
      const active=capture.draft.topology==='L-shaped'?['wall-north','wall-notch-vertical','wall-notch-horizontal','wall-east','wall-south','wall-west']:walls;
      const affected=new Set<string>([photo.primaryWallId,...photo.observedWallIds]);
      const openings:ReadonlyArray<SemanticOpening>=[...prior,...proposal.openings];
      for(const opening of openings){if(opening.wallId===null)active.forEach(wall=>affected.add(wall));else if((active as readonly string[]).includes(opening.wallId))affected.add(opening.wallId);}
      photo.semantics=proposal;photo.analysisStatus='complete';photo.analysisAttempts++;
      Object.assign(capture,{revision:capture.revision+1,state:'draft',confirmedRevision:null,roomHash:null,room:null,
        draft:{...capture.draft,wallReviews:capture.draft.wallReviews.filter((wall:string)=>!affected.has(wall)),
          ...(proposal.detectedFurniture!=='absent'?{furnitureAcknowledged:false}:{})}});
    } else if(path.endsWith('/draft')) {
      const b=body();expect(b.expectedRevision).toBe(capture.revision);
      const draft=authority('normalize',{before:capture.draft,after:b.draft});
      if(capture.draft.topology!==draft.topology){capture.calibrations=[];capture.photos.forEach((p:any)=>Object.assign(p,{semantics:null,observedWallIds:[],analysisStatus:'unknown'}));}
      Object.assign(capture,{revision:capture.revision+1,state:'draft',draft,confirmedRevision:null,roomHash:null,room:null});
    } else if(path.endsWith('/calibrate'))return route.fulfill({json:authority('calibrate',body())});
    else if(path.endsWith('/confirm')) {
      const checked=authority('confirm',capture);
      if(!checked.issues.length)Object.assign(capture,{state:'confirmed',confirmedRevision:capture.revision,roomHash:checked.hash,room:checked.room});
      return route.fulfill({json:{status:checked.issues.length?'review':'confirmed',capture,room:checked.room,issues:checked.issues}});
    } else if(path.endsWith('/generate')) {
      generations++;expect(capture.state).toBe('confirmed');
      const solved=await request.post('/api/arrangement-solve',{data:{room:capture.room,selections:[{id:'controlled-capture-selection',intents:[{id:'anchor-bed',kind:'centred_on',productId:'bed-prudence-tufted-queen-natural',wallId:capture.draft.topology==='L-shaped'?'wall-south':'wall-north',face:'back'}]}],policies:[{requestId:'anchor-bed',required:true,anchor:true}],clearanceWidthM:.6,maxCandidates:128}});
      expect(solved.status()).toBe(200);const design=await solved.json();
      const common={generationId:`controlled-capture-${generations}`,referenceId:'ref-01',providerModel:'controlled-offline',providerCalls:0,modelLatencyMs:0,usage:{known:false}};
      const result=design.status==='solved'?{...common,status:'solved',design}:{...common,status:'failed',code:'no-valid-design',detail:'The authoritative solver found no valid Design in its reported search.',designFailure:design};
      if(holdGeneration)await holdGeneration;
      try {await route.fulfill({json:{status:'generated',captureId:id,confirmedRevision:capture.revision,roomHash:capture.roomHash,result}});}finally{finished++;}
      return;
    } else if(method==='DELETE') {
      Object.assign(capture,{state:'deleting',revision:capture.revision+1,room:null,roomHash:null,confirmedRevision:null,photos:[],draft:blank,cleanupStatus:'pending'});
    }
    return route.fulfill({json:capture});
  });
  // Collection path has no trailing slash.
  await page.route('**/api/captures',route=>{privateRequests++;expect(route.request().headers().authorization).toBe('Bearer controlled-owner-jwt');expect(route.request().postDataJSON()).toEqual({consent:true});return route.fulfill({json:capture});});
  await page.goto('/capture');
  if(options.create!==false){
    await page.getByRole('checkbox',{name:/I understand private photo/}).check();
    await page.getByRole('button',{name:'Create private Capture'}).click();
    await expect(page.getByRole('heading',{name:'Declare your Room'})).toBeVisible();
  }
  return {get capture(){return capture;},get generations(){return generations;},get finished(){return finished;},get privateRequests(){return privateRequests;},authRequests,config,
    hold(promise:Promise<void>){holdGeneration=promise;},completeDeletion(){deleted=true;}};
}
export async function uploadWalls(page:Page,labels=['A','B','C','D']) {
  const hashes=new Set<string>();
  for(const [i,wall] of labels.entries()) {
    const data=await page.evaluate(index=>{const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=960;const c=canvas.getContext('2d')!;c.fillStyle=['#3d6854','#68443d','#485b7a','#796345','#375e81','#836170'][index]!;c.fillRect(0,0,1280,960);c.fillStyle='white';c.fillRect(100,100,200,200);return canvas.toDataURL('image/jpeg').split(',')[1]!;},i);
    const bytes=Buffer.from(data,'base64'),hash=createHash('sha256').update(bytes).digest('hex');
    expect(hashes.has(hash),'Each primary wall fixture must have distinct submitted JPEG bytes').toBe(false);
    hashes.add(hash);
    await page.getByLabel(`Wall ${wall} photo`,{exact:true}).setInputFiles({name:`synthetic-wall-${wall}.jpg`,mimeType:'image/jpeg',buffer:bytes});
    await expect(page.locator('.photo-list li')).toHaveCount(i+1);
    await expect(page.locator('.photo-list li').nth(i)).toContainText('accepted');
    await expect(page.getByLabel(`Wall ${wall} photo`,{exact:true})).toBeEnabled();
  }
}
export async function finalDimensions(page:Page,width='6',depth='4') {
  await page.getByLabel('Width (Wall A / C)',{exact:true}).fill(width);
  await page.getByLabel('Depth (Wall B / D)',{exact:true}).fill(depth);
  await page.getByLabel('Ceiling height',{exact:true}).fill('2.5');
  await page.getByRole('button',{name:'Save Room details',exact:true}).click();
  await expect(page.getByRole('checkbox',{name:/I checked and confirm all three/})).toBeEnabled();
  for(const label of await page.getByRole('checkbox',{name:'I reviewed this Opening and its operation.',exact:true}).all())await label.check();
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:'I reviewed every Opening on Wall '+wall+', including if there are none.',exact:true}).check();
  await page.getByRole('checkbox',{name:/I checked and confirm all three/}).check();
}
export async function screenshot(page:Page,name:string) {
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:join(evidence,`ticket-9-controlled-${name}.png`),fullPage:true});
  await page.screenshot({path:join(evidence,`ticket-9-controlled-${name}-viewport.png`)});
}

export async function uploadFour(page:Page) {
  await page.getByRole('radio',{name:'Bedroom',exact:true}).check();
  await page.getByRole('radio',{name:'Rectangle',exact:true}).check();
  await page.getByRole('button',{name:'Save Room details',exact:true}).click();
  await expect(page.getByRole('button',{name:'Save Room details',exact:true})).toBeDisabled();
  await uploadWalls(page);
}
