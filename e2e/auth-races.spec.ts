import { expect,test,type Page,type APIRequestContext } from '@playwright/test';
import type { Session } from '@supabase/supabase-js';

test.skip(process.env.E2E_LOCAL_SAVED_PROOF!=='1','Requires the controlled Auth/PostgreSQL harness.');
const key='sb-local-saved-auth-token';
test.beforeEach(async({page})=>{
  await page.route('https://local-saved.invalid/auth/v1/**',async route=>{
    const url=new URL(route.request().url());const response=await route.fetch({url:`http://127.0.0.1:55469${url.pathname}${url.search}`});await route.fulfill({response});
  });
});
async function stored(page:Page){return page.evaluate(key=>{const value=JSON.parse(localStorage.getItem(key)??'null');return value?{id:value.user.id as string,anonymous:value.user.is_anonymous as boolean}:null;},key);}
async function transition(page:Page,session:Session|null){
  await page.evaluate(async({key,session})=>{
    if(session)localStorage.setItem(key,JSON.stringify(session));else localStorage.removeItem(key);
    const channel=new BroadcastChannel(key);channel.postMessage({event:session?'SIGNED_IN':'SIGNED_OUT',session});
    await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));channel.close();
  },{key,session});
}
async function seed(request:APIRequestContext,session:Session){
  const design=await(await request.post('/api/design-resolution',{data:{fixtureId:'against-wall'}})).json();
  const saved=await request.post('/api/saved-designs',{headers:{Authorization:`Bearer ${session.access_token}`},data:{sessionId:design.swap.sessionId,expectedVersion:1,idempotencyKey:crypto.randomUUID(),consent:true}});
  expect(saved.status()).toBe(200);return (await saved.json()).id as string;
}
async function save(page:Page){
  await page.goto('/design');await page.getByRole('checkbox',{name:'I agree to retain this Design'}).check();
  await page.getByRole('button',{name:'Save Design',exact:true}).click();await page.getByRole('link',{name:'Open saved Design'}).click();
  await expect(page.getByRole('heading',{name:'Reopened Design'})).toBeVisible();
  return new URL(page.url()).pathname.split('/').at(-1)!;
}
async function sendLink(page:Page,email:string){
  await page.getByRole('textbox',{name:'Email',exact:true}).fill(email);await page.getByRole('button',{name:'Link email to this account'}).click();
  await page.getByRole('textbox',{name:'Email verification code'}).fill('123456');
}
for(const action of ['signup','link','return'] as const)for(const change of ['owner','signout','navigation'] as const)test(`held ${action} response cannot replace ${change} authority`,async({page,request})=>{
  const email=`race-${crypto.randomUUID()}@example.test`;
  let oldId='',oldSession:Session|null=null;
  if(action!=='signup'){
    oldId=await save(page);
    if(action==='return'){
      await sendLink(page,email);await page.getByRole('button',{name:'Verify email code'}).click();
      await expect(page.getByText('Email linked and refreshed.',{exact:false})).toBeVisible();
      await page.getByRole('button',{name:'Sign out of this account'}).click();
      await page.getByRole('textbox',{name:'Email',exact:true}).fill(email);await page.getByRole('checkbox',{name:'I choose to switch'}).check();
      await page.getByRole('button',{name:'Send returning sign-in code'}).click();await page.getByRole('textbox',{name:'Email verification code'}).fill('123456');
    }else await sendLink(page,email);
  }else await page.goto('/design');
  const before=await stored(page);
  if(action==='link')await page.evaluate(({owner})=>localStorage.setItem(`furnitureos.capture.${owner}`,'existing-capture-pointer'),{owner:before!.id});
  let release!:()=>void,started!:()=>void,delivered!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});const requested=new Promise<void>(resolve=>{started=resolve;});const released=new Promise<void>(resolve=>{delivered=resolve;});
  await page.route(`https://local-saved.invalid/auth/v1/${action==='signup'?'signup':'verify'}`,async route=>{
    const response=await route.fetch({url:`http://127.0.0.1:55469/auth/v1/${action==='signup'?'signup':'verify'}`});
    oldSession=await response.json() as Session;
    if(action==='signup')oldId=await seed(request,oldSession!);
    started();await held;
    try{await route.fulfill({response});}catch{/* Cancellation aborts the obsolete SDK fetch. */}finally{delivered();}
  },{times:1});
  let savePosts=0;page.on('request',req=>{if(new URL(req.url()).pathname==='/api/saved-designs'&&req.method()==='POST')savePosts++;});
  try{
    if(action==='signup'){
      await page.getByRole('checkbox',{name:'I agree to retain this Design'}).check();await page.getByRole('button',{name:'Save Design',exact:true}).click();
    }else await page.getByRole('button',{name:'Verify email code'}).click();
    await requested;
    let expected=before,newId='';
    if(change==='owner'){
      const next=await(await request.post('http://127.0.0.1:55469/auth/v1/signup',{data:{}})).json() as Session;
      newId=await seed(request,next);await transition(page,next);expected={id:next.user.id,anonymous:true};
    }else if(change==='signout'){await transition(page,null);expected=null;}
    else if(action==='signup')await page.getByRole('link',{name:'Saved Designs and account recovery'}).click();
    else await page.getByRole('link',{name:'Room preview',exact:true}).click();
    if(change!=='navigation')await expect(page.getByRole('heading',{name:'Reopened Design'})).toHaveCount(0);
    release();await released;
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
    expect(await stored(page)).toEqual(expected);
    await expect(page.getByText('Email linked and refreshed.',{exact:false})).toHaveCount(0);
    await expect(page.getByText('Returning account verified.',{exact:false})).toHaveCount(0);
    if(action==='link')expect(await page.evaluate(owner=>localStorage.getItem(`furnitureos.capture.${owner}`),before!.id)).toBe(change==='navigation'?'existing-capture-pointer':null);
    // Navigate through the live SDK after response delivery: this also catches
    // a stale SDK notification that could otherwise reopen an old private scene.
    await page.goto('/saved');await expect(page.getByRole('heading',{name:'Saved Designs',exact:true})).toBeVisible();
    await expect.poll(()=>stored(page)).toEqual(expected);
    if(change!=='navigation'||action!=='link'){
      await expect(page.locator(`.saved-list a[href="/saved/${oldId}"]`)).toHaveCount(0);
      await expect(page.getByRole('heading',{name:'Reopened Design'})).toHaveCount(0);
    }
    if(newId)await expect(page.locator(`.saved-list a[href="/saved/${newId}"]`)).toBeVisible();
    await expect(page.getByText('Email linked and refreshed.',{exact:false})).toHaveCount(0);
    await expect(page.getByText('Returning account verified.',{exact:false})).toHaveCount(0);
    expect(savePosts).toBe(0);
    expect(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('furnitureos.saved.pending.')).length)).toBe(0);
  }finally{release();}
});
