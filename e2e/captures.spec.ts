import { expect, test, type Page, type APIRequestContext } from '@playwright/test';
import type { CaptureSemanticProposal, SemanticOpening } from '../src/shared/api/types';
import { controlled, uploadFour, finalDimensions, screenshot, evidence } from './capture-fixture';
import { join } from 'node:path';
import { writeFileSync } from 'node:fs';
const walls=['wall-north','wall-east','wall-south','wall-west'] as const;

function semanticEvidence(wall:SemanticOpening['wallId']|'none'):CaptureSemanticProposal {
  return {openings:wall==='none'?[]:[{id:'replacement-observation',wallId:wall,kind:'door',location:'middle',visibility:'partial',
    direction:'unknown',angle:'unknown',hingeSide:'unknown',description:'Controlled prior or replacement proposal'}],detectedFurniture:'absent',observation:'partial'};
}
const replacements:ReadonlyArray<{name:string;old:SemanticOpening['wallId'];next:SemanticOpening['wallId']|'none';remaining:ReadonlyArray<typeof walls[number]>}>=[
  {name:'removed',old:'wall-south',next:'none',remaining:['wall-east','wall-west']},
  {name:'moved',old:'wall-south',next:'wall-east',remaining:['wall-west']},
  {name:'old unknown resolved',old:null,next:'wall-east',remaining:[]},
  {name:'old unknown empty',old:null,next:'none',remaining:[]},
  {name:'new unknown',old:'wall-south',next:null,remaining:[]},
  {name:'both unknown',old:null,next:null,remaining:[]},
];
for(const scenario of replacements)test(`reanalysis ${scenario.name} clears prior/current wall reviews before reconfirmation`,async({page,request})=>{
  const flow=await controlled(page,request,{analysisProposals:[semanticEvidence(scenario.old),semanticEvidence(scenario.next)]});
  await uploadFour(page);
  await page.getByRole('radio',{name:'Bedroom',exact:true}).check();await page.getByRole('radio',{name:'Rectangle',exact:true}).check();
  await page.getByRole('button',{name:'Analyze this photo'}).first().click();
  await expect(page.getByRole('button',{name:'Analyze this photo'}).first()).toBeEnabled();
  expect(flow.capture.photos[0].semantics).toEqual(semanticEvidence(scenario.old));
  await page.getByRole('button',{name:'Add missed Opening'}).click();
  await page.getByLabel('Opening 1 wall',{exact:true}).selectOption('wall-west');
  await page.getByLabel('Opening 1 type',{exact:true}).selectOption('window');
  for(const [label,value] of [['Distance from wall start','1'],['Width','0.7'],['Bottom / sill height','1'],['Height','0.8'],['Inward clearance','0']])await page.getByLabel(`Opening 1 ${label}`,{exact:true}).fill(value!);
  await page.getByRole('checkbox',{name:'I reviewed this Opening and its operation.'}).check();
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${wall}, including if there are none.`}).check();
  await page.getByRole('checkbox',{name:'I acknowledge the empty-Room assumption.'}).check();await finalDimensions(page,'6.4','4.2');
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await page.getByRole('radio',{name:/Soft neutrals and warm wood/}).check();
  const before=JSON.parse(JSON.stringify(flow.capture));
  await page.getByRole('button',{name:'Analyze this photo'}).first().click();
  await expect(page.getByRole('button',{name:'Generate confirmed Room',exact:true})).toBeDisabled();
  expect(flow.capture.photos[0].analysisAttempts).toBe(2);
  expect(flow.capture.draft.wallReviews).toEqual(scenario.remaining);
  for(const [i,wall] of walls.entries()){
    const review=page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${'ABCD'[i]}, including if there are none.`});
    if(scenario.remaining.includes(wall))await expect(review).toBeChecked();else await expect(review).not.toBeChecked();
  }
  expect(flow.capture.draft.openings).toEqual(before.draft.openings);
  for(const key of ['widthM','depthM','heightM','dimensionsConfirmed','dimensionEvidence','furnitureAcknowledged'])expect(flow.capture.draft[key]).toEqual(before.draft[key]);
  expect(flow.capture.revision).toBe(before.revision+1);expect(flow.capture.state).toBe('draft');
  expect(flow.capture.room).toBeNull();expect(flow.capture.roomHash).toBeNull();expect(flow.capture.confirmedRevision).toBeNull();
  expect(flow.generations).toBe(0);
  // Reviewing only new/associated walls still cannot reuse old wall-C acknowledgement.
  await page.getByRole('checkbox',{name:'I reviewed every Opening on Wall A, including if there are none.'}).check();
  if(scenario.next!==null&&scenario.next!=='none')await page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${'ABCD'[(walls as readonly string[]).indexOf(scenario.next)]}, including if there are none.`}).check();
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByRole('alert')).toContainText('Review the complete Opening inventory on every wall');
  await expect(page.getByRole('button',{name:'Generate confirmed Room',exact:true})).toBeDisabled();expect(flow.generations).toBe(0);
  if(scenario.name==='removed'){
    await page.getByRole('alert').scrollIntoViewIfNeeded();await screenshot(page,'prior-wall-review-required');
  }
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${wall}, including if there are none.`}).check();
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Validated furnished Room'})).toBeVisible();expect(flow.generations).toBe(1);
});

test('local topology change cancels an in-flight calibration without reusing its provenance',async({page,request})=>{
  const flow=await controlled(page,request);await uploadFour(page);
  await page.getByText('Optional known-size reference prefill',{exact:true}).click();
  await page.getByLabel('Canonical photo',{exact:true}).selectOption(flow.capture.photos[0].id);
  await expect(page.getByAltText('Private canonical photo for user-authored calibration')).toBeVisible();
  const marks=[[100,100],[300,100],[300,300],[100,300],[100,350],[900,350]];
  for(const [i,point] of marks.entries())for(const [axis,name] of ['x','y'].entries())await page.getByLabel(`Mark ${i+1} ${name}`,{exact:true}).fill(String(point[axis]));
  await page.getByRole('checkbox',{name:/I confirm known size, ordered marks/}).check();
  let release!:()=>void,started!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});
  const entered=new Promise<void>(resolve=>{started=resolve;});
  await page.route('**/api/captures/*/calibrate',async route=>{
    started();await held;
    // The request has deliberately been aborted by the topology transition.
    await route.fallback().catch(()=>{});
  });
  try {
    await page.getByRole('button',{name:'Calculate provisional estimate',exact:true}).click();
    await entered;
    const aborted=page.waitForEvent('requestfailed',{predicate:req=>req.url().endsWith('/calibrate')});
    await page.getByRole('radio',{name:'L-shaped',exact:true}).check();
    await aborted;
    await expect(page.getByLabel('Mark 1 x',{exact:true})).toHaveValue('');
    await expect(page.getByLabel('Overall width',{exact:true})).toHaveValue('');
    await expect(page.getByText('Provisional reference origin; verify or override.',{exact:true})).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Review and confirm Room',exact:true})).toBeDisabled();
  } finally {release();}
});

test('controlled Capture corrections, real homography and confirmed nonfixture solver scene on desktop/mobile',async({page,request})=>{
  await page.setViewportSize({width:1440,height:1000});
  const flow=await controlled(page,request);await uploadFour(page);
  await expect(page.getByLabel('Width (Wall A / C)',{exact:true})).toHaveValue('');
  await page.getByRole('radio',{name:'Bedroom',exact:true}).check();
  await page.getByRole('radio',{name:'other',exact:true}).check();
  await expect(page.getByText('This topology is unsupported.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Return to shape selection'}).click();
  await page.getByRole('radio',{name:'Rectangle',exact:true}).check();
  await page.getByRole('button',{name:'Analyze this photo'}).first().click();
  await expect(page.getByText('Detected Furniture / unresolved detection')).toBeVisible();
  await page.getByRole('button',{name:'Add proposal to inventory'}).click();
  await page.getByRole('button',{name:'Remove false Opening'}).click();
  await page.getByRole('button',{name:'Add missed Opening'}).click();
  await page.getByLabel('Opening 1 wall',{exact:true}).selectOption('wall-south');
  await page.getByLabel('Opening 1 type',{exact:true}).selectOption('door');
  for(const [label,value] of [['Distance from wall start','0.3'],['Width','0.8'],['Bottom / sill height','0'],['Height','2'],['Inward clearance','0.2']])await page.getByLabel(`Opening 1 ${label}`,{exact:true}).fill(value!);
  await page.getByRole('checkbox',{name:'I reviewed this Opening and its operation.'}).check();
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${wall}, including if there are none.`}).check();
  await page.getByRole('checkbox',{name:'I acknowledge the empty-Room assumption.'}).check();
  await finalDimensions(page);
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByRole('alert')).toContainText('inward 90-degree');
  expect(flow.generations).toBe(0);
  await screenshot(page,'desktop-required-swing');
  await page.getByLabel('Opening 1 door direction',{exact:true}).selectOption('inward');
  await page.getByLabel('Opening 1 swing angle',{exact:true}).selectOption('90');
  await page.getByLabel('Opening 1 hinge side',{exact:true}).selectOption('end');
  await page.getByRole('checkbox',{name:'I reviewed this Opening and its operation.'}).check();
  // Remove typed width to exercise honest reference prefill. Other typed values survive.
  await page.getByLabel('Width (Wall A / C)',{exact:true}).fill('');
  await page.getByRole('button',{name:'Save Room details',exact:true}).click();
  await expect(page.getByRole('button',{name:'Save Room details',exact:true})).toBeDisabled();
  await page.getByText('Optional known-size reference prefill',{exact:true}).click();
  await page.getByLabel('Canonical photo',{exact:true}).selectOption(flow.capture.photos[0].id);
  await page.getByLabel('Reference',{exact:true}).selectOption('measured');
  await page.getByLabel('Reference width (m)',{exact:true}).fill('1');
  await page.getByLabel('Reference height (m)',{exact:true}).fill('1');
  await expect(page.getByAltText('Private canonical photo for user-authored calibration')).toBeVisible();
  // Endpoints must be visible inside the image: a 200 px reference gives a 4 m edge.
  const visible=[[100,100],[300,100],[300,300],[100,300],[100,350],[900,350]];
  for(const [i,point] of visible.entries())for(const [axis,name] of ['x','y'].entries())await page.getByLabel(`Mark ${i+1} ${name}`,{exact:true}).fill(String(point[axis]));
  await page.getByRole('checkbox',{name:/I confirm known size, ordered marks/}).check();
  await page.getByRole('button',{name:'Calculate provisional estimate'}).click();
  await expect.poll(async()=>Number(await page.getByLabel('Width (Wall A / C)',{exact:true}).inputValue())).toBeCloseTo(4,8);
  await expect(page.getByLabel('Depth (Wall B / D)',{exact:true})).toHaveValue('4');
  await page.getByLabel('Width (Wall A / C)',{exact:true}).fill('6');
  await page.getByLabel('Manual override reason',{exact:true}).fill('Tape measured 6 m; reference setup was synthetic for offline proof.');
  await page.getByRole('button',{name:'Save Room details',exact:true}).click();
  await expect(page.getByRole('checkbox',{name:/I checked and confirm all three/})).toBeEnabled();
  await page.getByRole('checkbox',{name:'I reviewed this Opening and its operation.',exact:true}).check();
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:'I reviewed every Opening on Wall '+wall+', including if there are none.',exact:true}).check();
  await page.getByRole('checkbox',{name:/I checked and confirm all three/}).check();
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await screenshot(page,'desktop-corrected-preview');
  await page.setViewportSize({width:390,height:844});
  await page.getByLabel('Opening 1 wall',{exact:true}).scrollIntoViewIfNeeded();await screenshot(page,'mobile-corrected-openings');
  await page.getByRole('heading',{name:'Confirmed Room',exact:true}).scrollIntoViewIfNeeded();await screenshot(page,'mobile-confirmed-preview');
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('radio',{name:/Soft neutrals and warm wood/}).check();
  await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Validated furnished Room'})).toBeVisible();
  await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>window.__furnitureos?.usefulView.status==='complete',undefined,{timeout:60000});
  const facts=await page.evaluate(()=>JSON.parse(JSON.stringify(window.__furnitureos)));
  expect(facts.generationId).toBe('controlled-capture-1:A');
  expect(Object.values(facts.instances).every((p:any)=>p.screenVisible&&p.actualFrameRendered&&p.activeMeshCount>0)).toBe(true);
  expect(flow.capture.room.floorPolygon).toEqual([[-3,-2],[-3,2],[3,2],[3,-2]]);
  writeFileSync(join(evidence,'ticket-9-controlled-scene.json'),JSON.stringify({room:flow.capture.room,facts},null,2)+'\n');
  await screenshot(page,'desktop-solved');
  await page.setViewportSize({width:390,height:844});await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();await screenshot(page,'mobile-solved');
  // New semantics are new evidence requiring renewed explicit review, even after solving.
  const beforeAnalysis=JSON.parse(JSON.stringify(flow.capture));
  await page.getByRole('button',{name:'Analyze this photo'}).first().click();
  await expect(page.getByRole('checkbox',{name:'I reviewed every Opening on Wall A, including if there are none.'})).not.toBeChecked();
  await expect(page.getByRole('checkbox',{name:'I acknowledge the empty-Room assumption.'})).not.toBeChecked();
  expect(flow.capture.revision).toBe(beforeAnalysis.revision+1);
  expect(flow.capture.state).toBe('draft');expect(flow.capture.room).toBeNull();expect(flow.capture.roomHash).toBeNull();expect(flow.capture.confirmedRevision).toBeNull();
  expect(flow.capture.draft.openings).toEqual(beforeAnalysis.draft.openings);
  expect(flow.capture.draft.dimensionEvidence).toEqual(beforeAnalysis.draft.dimensionEvidence);
  for(const key of ['widthM','depthM','heightM','dimensionsConfirmed'])expect(flow.capture.draft[key]).toEqual(beforeAnalysis.draft[key]);
  for(const wall of 'BCD')await expect(page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${wall}, including if there are none.`})).toBeChecked();
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Validated furnished Room'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Generate confirmed Room',exact:true})).toBeDisabled();
  expect(flow.generations).toBe(1);
  await screenshot(page,'mobile-new-analysis-review');
  await page.getByRole('checkbox',{name:'I reviewed every Opening on Wall A, including if there are none.'}).check();
  await page.getByRole('checkbox',{name:'I acknowledge the empty-Room assumption.'}).check();
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Generate confirmed Room',exact:true})).toBeEnabled();
  expect(flow.generations).toBe(1);
  // A new confirmed tiny Room exercises real no-fit without mislabelling invalid data.
  await page.getByLabel('Opening 1 Distance from wall start',{exact:true}).fill('0.1');
  await page.getByRole('checkbox',{name:'I reviewed this Opening and its operation.'}).check();
  await page.getByLabel('Manual override reason',{exact:true}).fill('Synthetic impossible-fit test: final Room is 1 m by 1 m.');
  await finalDimensions(page,'1','1');
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry generation explicitly'})).toBeVisible();
  await expect(page.getByText(/No valid Design (fits|found)/)).toBeVisible();
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await screenshot(page,'mobile-no-fit');
  await page.setViewportSize({width:1440,height:1000});await screenshot(page,'desktop-no-fit');
  await page.getByRole('button',{name:'Delete Capture',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Deletion pending'})).toBeVisible();
  await page.getByRole('button',{name:'Check status'}).click();
  await expect(page.getByText(/Working on this request/)).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Deletion pending'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Check status'})).toBeEnabled();
  flow.completeDeletion();
  await page.getByRole('button',{name:'Check status'}).click();
  await expect(page.getByText('Capture deletion completed.')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Deletion pending'})).toHaveCount(0);
  expect(flow.generations).toBe(2);
});

for(const source of ['restored','created'] as const)for(const flag of [false,null])test(`${source} ${flag===false?'permanent':'missing anonymity flag'} identity cannot restore or create private data`,async({page,request})=>{
  const flow=await controlled(page,request,{create:false,...(source==='restored'?{restoredFlag:flag}:{createdFlag:flag})});
  if(source==='restored')await expect(page.getByText('Capture requires an anonymous account. Your existing account has not been changed.')).toBeVisible();
  await page.getByRole('checkbox',{name:/I understand private photo/}).check();
  await page.getByRole('button',{name:'Create private Capture'}).click();
  await expect(page.getByText('Capture requires an anonymous account. Your existing account has not been changed.')).toBeVisible();
  expect(flow.privateRequests).toBe(0);
  expect(flow.authRequests.filter(req=>req.path.endsWith('/signup'))).toHaveLength(source==='created'?1:0);
  expect(flow.authRequests.some(req=>req.path.endsWith('/logout')||(req.path.endsWith('/user')&&req.method!=='GET'))).toBe(false);
  await expect(page.getByRole('heading',{name:'Declare your Room'})).toHaveCount(0);
  await expect(page.getByLabel('Wall A photo',{exact:true})).toHaveCount(0);
});

test('activation failure has no synthetic ownership or upload path',async({page})=>{
  await page.route('**/api/captures/config',route=>route.fulfill({json:{storageReady:false,analysisAvailable:false,generationAvailable:false,detail:'Anonymous Auth is disabled; activation proof remains unrun.'}}));
  await page.goto('/capture');await expect(page.getByRole('heading',{name:'Capture is unavailable right now'})).toBeVisible();
  await expect(page.getByRole('link',{name:'explore Room preview',exact:true})).toBeVisible();
  await expect(page.getByTestId('capture-page')).not.toContainText(/Anonymous Auth|RLS|configuration/);
  await expect(page.getByRole('button',{name:'Create private Capture'})).toHaveCount(0);
});

test('cross-tab anonymous identity loss clears private state and discards late solved response',async({page,request})=>{
  const flow=await controlled(page,request);await uploadFour(page);
  await page.getByRole('radio',{name:'Bedroom',exact:true}).check();await page.getByRole('radio',{name:'Rectangle',exact:true}).check();
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${wall}, including if there are none.`}).check();
  await page.getByRole('checkbox',{name:'I acknowledge the empty-Room assumption.'}).check();await finalDimensions(page);
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await page.getByRole('radio',{name:/Soft neutrals and warm wood/}).check();
  let release!:()=>void;flow.hold(new Promise<void>(resolve=>{release=resolve;}));
  await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();
  await expect.poll(()=>flow.generations).toBe(1);
  // Installed GoTrueClient uses this same-key BroadcastChannel for other-tab signout.
  await page.evaluate(()=>{const key=Object.keys(localStorage).find(k=>k.startsWith('sb-')&&k.endsWith('-auth-token'));if(!key)throw new Error('real SDK session missing');localStorage.removeItem(key);const channel=new BroadcastChannel(key);channel.postMessage({event:'SIGNED_OUT',session:null});setTimeout(()=>channel.close(),100);});
  await expect(page.getByText(/Anonymous account access was lost. Your private preview was cleared/)).toBeVisible();
  release();
  await expect.poll(()=>flow.finished).toBe(1);
  await expect(page.getByRole('heading',{name:'Declare your Room'})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Validated furnished Room'})).toHaveCount(0);
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
});

for(const flag of [false,null])test(`same UUID ${flag===false?'permanent':'missing anonymity flag'} Auth event clears private state and late generation`,async({page,request})=>{
  const flow=await controlled(page,request);await uploadFour(page);
  await page.getByRole('radio',{name:'Bedroom',exact:true}).check();await page.getByRole('radio',{name:'Rectangle',exact:true}).check();
  for(const wall of 'ABCD')await page.getByRole('checkbox',{name:`I reviewed every Opening on Wall ${wall}, including if there are none.`}).check();
  await page.getByRole('checkbox',{name:'I acknowledge the empty-Room assumption.'}).check();await finalDimensions(page);
  await page.getByRole('button',{name:'Review and confirm Room'}).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
  await page.getByRole('radio',{name:/Soft neutrals and warm wood/}).check();
  let release!:()=>void;flow.hold(new Promise<void>(resolve=>{release=resolve;}));
  await page.getByRole('button',{name:'Generate confirmed Room',exact:true}).click();
  await expect.poll(()=>flow.generations).toBe(1);
  // Real installed SDK event with unchanged UUID; mutable metadata remains true.
  await page.evaluate(flag=>{
    const key=Object.keys(localStorage).find(k=>k.startsWith('sb-')&&k.endsWith('-auth-token'));if(!key)throw new Error('real SDK session missing');
    const session=JSON.parse(localStorage.getItem(key)!);
    if(flag===null)delete session.user.is_anonymous;else session.user.is_anonymous=flag;
    localStorage.setItem(key,JSON.stringify(session));
    const channel=new BroadcastChannel(key);channel.postMessage({event:'USER_UPDATED',session});setTimeout(()=>channel.close(),100);
  },flag);
  await expect(page.getByText('Capture requires an anonymous account. Your existing account has not been changed.')).toBeVisible();
  release();await expect.poll(()=>flow.finished).toBe(1);
  await expect(page.getByRole('heading',{name:'Declare your Room'})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Validated furnished Room'})).toHaveCount(0);
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect(page.getByLabel('Wall A photo',{exact:true})).toHaveCount(0);
  expect(flow.authRequests.some(req=>req.path.endsWith('/logout')||(req.path.endsWith('/user')&&req.method!=='GET'))).toBe(false);
});
