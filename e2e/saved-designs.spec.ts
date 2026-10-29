import { expect, test, type Page } from '@playwright/test';
import type { Session } from '@supabase/supabase-js';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { uploadFour, finalDimensions } from './capture-fixture';

test.skip(process.env.E2E_LOCAL_SAVED_PROOF !== '1', 'Requires the explicitly controlled local Auth/PostgreSQL harness; never a hosted check.');
test.beforeEach(async ({ page }) => {
  // Only the external Auth HTTP boundary is controlled. Application APIs and
  // persistence execute unchanged against the isolated PostgreSQL database.
  await page.route('https://local-saved.invalid/auth/v1/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `http://127.0.0.1:55469${url.pathname}${url.search}` });
    await route.fulfill({ response });
  });
});

async function switchOwner(page: Page, next: Session) {
  await page.evaluate(async next => {
    const key=Object.keys(localStorage).find(key=>key.startsWith('sb-')&&key.endsWith('-auth-token'))??'sb-local-saved-auth-token';
    localStorage.setItem(key,JSON.stringify(next));
    const channel=new BroadcastChannel(key);channel.postMessage({event:'SIGNED_IN',session:next});
    await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
    channel.close();
  },next);
}

test('anonymous save, conflict preservation, verified linking, reload and returning OTP retain the Design', async ({ page }, testInfo) => {
  await page.goto('/design');
  await expect(page.getByTestId('stage')).toBeVisible();
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open saved Design' })).toBeVisible();
  await page.getByRole('link', { name: 'Open saved Design' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  const savedUrl = page.url();
  await page.waitForFunction(() => Object.values(window.__furnitureos?.instances ?? {}).some(instance => instance.ready));
  const before = await page.evaluate(() => Object.fromEntries(Object.entries(window.__furnitureos!.instances).map(([id, value]) => [id, { productId: value.productId, placement: value.publishedPlacement }])));
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill('taken@example.test');
  await page.getByRole('button', { name: 'Link email to this account' }).click();
  await expect(page.getByText('This email already belongs', { exact: false })).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill('person@example.test');
  await page.getByRole('button', { name: 'Link email to this account' }).click();
  await page.getByRole('textbox', { name: 'Email verification code' }).fill('123456');
  await page.getByRole('button', { name: 'Verify email code' }).click();
  await expect(page.getByText('Email linked and refreshed.', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => Object.fromEntries(Object.entries(window.__furnitureos?.instances ?? {}).map(([id, value]) => [id, { productId: value.productId, placement: value.publishedPlacement }])))).toEqual(before);
  const root = process.env.FURNITUREOS_EVIDENCE_DIR!;
  await mkdir(root, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: join(root, `saved-desktop-${testInfo.retry}.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: join(root, `saved-mobile-${testInfo.retry}.png`), fullPage: true });
  await page.getByRole('button', { name: 'Sign out of this account' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill('person@example.test');
  await page.getByRole('checkbox', { name: 'I choose to switch' }).check();
  await page.getByRole('button', { name: 'Send returning sign-in code' }).click();
  await page.getByRole('textbox', { name: 'Email verification code' }).fill('123456');
  await page.getByRole('button', { name: 'Verify email code' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  expect(page.url()).toBe(savedUrl);
  await page.getByRole('button', { name: 'Delete saved Design', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toHaveCount(0);
  await page.goto(savedUrl);
  await expect(page.getByRole('alert')).toContainText('deleted');
  await expect(page.getByTestId('stage')).toHaveCount(0);
});

test('lost committed save response recovers from the persisted pending key after reload', async ({ page }) => {
  await page.goto('/design');
  await page.route('**/api/saved-designs', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    const committed = await route.fetch();
    expect(committed.status()).toBe(200);
    await route.abort('failed');
  }, { times: 1 });
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await expect(page.locator('.saved-controls [role=status]')).toBeVisible();
  await page.goto('/saved');
  await page.reload();
  await page.getByRole('button', { name: 'Recover pending save' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await expect(page.locator('.saved-list li')).toHaveCount(1);
});

test('different UUID cancels a held restore and clears previous-owner hints', async ({ page }) => {
  await page.goto('/design');
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await page.getByRole('link', { name: 'Open saved Design' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  const savedId = new URL(page.url()).pathname.split('/').at(-1)!;
  let release!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  let started!: () => void;
  const requested = new Promise<void>(resolve => { started = resolve; });
  await page.route(`**/api/saved-designs/${savedId}`, async route => {
    const response = await route.fetch(); started(); await hold;
    await route.fulfill({ response }).catch(() => { /* An identity change aborts the obsolete fetch. */ });
  }, { times: 1 });
  try {
    await page.reload(); await requested;
    const next = await (await page.request.post('http://127.0.0.1:55469/auth/v1/signup', { data: {} })).json();
    const previous = await page.evaluate(next => {
      const key = Object.keys(localStorage).find(key => key.startsWith('sb-') && key.endsWith('-auth-token'))!;
      const old = JSON.parse(localStorage.getItem(key)!).user.id as string;
      localStorage.setItem(`furnitureos.capture.${old}`, 'old-capture-pointer');
      localStorage.setItem(`furnitureos.saved.pending.${old}`, '{}');
      localStorage.setItem(key, JSON.stringify(next));
      const channel = new BroadcastChannel(key); channel.postMessage({ event: 'SIGNED_IN', session: next }); setTimeout(() => channel.close(), 100);
      return old;
    }, next);
    await expect(page.getByRole('alert')).toContainText('unavailable');
    release();
    await expect(page.getByTestId('stage')).toHaveCount(0);
    await expect(page.locator('.saved-list li')).toHaveCount(0);
    expect(await page.evaluate(owner => [localStorage.getItem(`furnitureos.capture.${owner}`), localStorage.getItem(`furnitureos.saved.pending.${owner}`)], previous)).toEqual([null, null]);
  } finally { release(); }
});

test('expired pending requests are discarded without automatic new-key retries', async ({ page }) => {
  await page.goto('/design');
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await page.getByRole('link', { name: 'Open saved Design' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await page.evaluate(() => {
    const authKey = Object.keys(localStorage).find(key => key.startsWith('sb-') && key.endsWith('-auth-token'))!;
    const owner = JSON.parse(localStorage.getItem(authKey)!).user.id;
    localStorage.setItem(`furnitureos.saved.pending.${owner}`, JSON.stringify({ version: 1, at: Date.now() - 86400001,
      body: { sessionId: 'expired-source', expectedVersion: 1, idempotencyKey: 'expired-pending-key', consent: true, policyVersion: 'saved-until-deleted-v1' } }));
  });
  let posts = 0;
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/saved-designs' && request.method() === 'POST') posts++; });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Recover pending save' })).toHaveCount(0);
  expect(posts).toBe(0);
  await expect(page.locator('.saved-list li')).toHaveCount(1);
});

test('saving locks Swap/Nudge and prevents another unchanged-session save', async ({ page }) => {
  await page.goto('/design');
  let release!: () => void, started!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { started = resolve; });
  let posts = 0;
  await page.route('**/api/saved-designs', async route => {
    posts++; started(); await hold;
    const response = await route.fetch(); await route.fulfill({ response });
  }, { times: 1 });
  try {
    await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
    await page.getByRole('button', { name: 'Save Design', exact: true }).click();
    await requested;
    await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Prepare Nudge' })).toBeDisabled();
    release();
    await expect(page.getByRole('link', { name: 'Open saved Design' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Design saved', exact: true })).toBeDisabled();
    expect(posts).toBe(1);
  } finally { release(); }
});

test('stale save refreshes the current server version before explicit retry', async ({ page, request }) => {
  await page.goto('/design');
  const swap = page.getByTestId('swap-controls');
  await expect(swap).toHaveAttribute('data-version', '1');
  const session = (await swap.getAttribute('data-session-id'))!;
  const current = await (await request.get(`/api/swaps/${session}`)).json();
  const instance = current.design.placements[0].instanceId;
  const choices = await (await request.get(`/api/swaps/${session}/candidates`, { params: { expectedVersion: 1, instanceId: instance } })).json();
  const accepted = await (await request.post('/api/swaps', { data: { sessionId: session, expectedVersion: 1, instanceId: instance, replacementProductId: choices.candidates[0].product.id } })).json();
  expect(accepted.status).toBe('accepted');
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await expect(swap).toHaveAttribute('data-version', '2');
  await expect(page.getByText('The Design changed. Review the refreshed Design and save again.')).toBeFocused();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await page.getByRole('link', { name: 'Open saved Design' }).click();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await page.waitForFunction(() => Object.values(window.__furnitureos?.instances ?? {}).some(instance => instance.ready));
  await expect.poll(()=>page.evaluate(()=>Object.values(window.__furnitureos?.instances??{})[0]?.productId)).toBe(accepted.design.placements[0].productId);
});

test('actual captured Design and accepted Swap keep their Capture association through linking, reload and original deletion', async ({ page, request }) => {
  await page.goto('/capture');
  await page.getByRole('checkbox', { name: /I understand private photo/ }).check();
  await page.getByRole('button', { name: 'Create private Capture' }).click();
  await uploadFour(page);
  await page.getByRole('checkbox', { name: 'I acknowledge the empty-Room assumption.' }).check();
  await finalDimensions(page);
  const confirmedResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/confirm') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Review and confirm Room', exact: true }).click();
  const capture = (await (await confirmedResponse).json()).capture;
  const originalOwner = await page.evaluate(()=>JSON.parse(localStorage.getItem('sb-local-saved-auth-token')!).user.id as string);
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  await page.getByRole('button', { name: 'Generate confirmed Room', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Validated furnished Room' })).toBeVisible();
  await page.getByRole('button', { name: 'Check compatible Products', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Compatible Product' })).toBeVisible();
  const swapped = page.waitForResponse(response => new URL(response.url()).pathname === '/api/swaps' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Swap Product', exact: true }).click();
  const accepted = await (await swapped).json(); expect(accepted.status).toBe('accepted');
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  const archiveResponse = page.waitForResponse(response => /\/api\/saved-designs\/[^/]+$/.test(new URL(response.url()).pathname) && !response.url().endsWith('/config') && response.request().method() === 'GET');
  await page.getByRole('link', { name: 'Open saved Design' }).click();
  const archive = await (await archiveResponse).json();
  expect(archive.capture).toEqual({ id: capture.id, confirmedRevision: capture.revision, roomHash: capture.roomHash });
  expect(archive.design.placements).toEqual(accepted.design.placements);
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill('capture-person@example.test');
  await page.getByRole('button', { name: 'Link email to this account' }).click();
  await page.getByRole('textbox', { name: 'Email verification code' }).fill('123456');
  await page.getByRole('button', { name: 'Verify email code' }).click();
  await expect(page.getByText('Email linked and refreshed.', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await expect(page.getByText(`Archived confirmed Capture ${capture.id}, revision ${capture.revision}. Original photos are separate.`)).toBeVisible();
  expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('sb-local-saved-auth-token')!).user.id as string)).toBe(originalOwner);
  expect(await page.evaluate(owner=>localStorage.getItem(`furnitureos.capture.${owner}`),originalOwner)).toBe(capture.id);
  const token = await page.evaluate(() => {
    const key = Object.keys(localStorage).find(key => key.startsWith('sb-') && key.endsWith('-auth-token'))!;
    return JSON.parse(localStorage.getItem(key)!).access_token as string;
  });
  const deletion = await request.delete(`/api/captures/${capture.id}`, { headers: { Authorization: `Bearer ${token}` }, data: { expectedRevision: capture.revision } });
  expect(deletion.status()).toBe(200);
  const restoredResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/saved-designs/${archive.id}` && response.request().method() === 'GET');
  await page.reload();
  const restored = await (await restoredResponse).json();
  expect(restored.capture).toEqual(archive.capture);
  expect(restored.design.placements).toEqual(accepted.design.placements);
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
});

test('a late completed Save clears only its own pending operation hint', async ({ page }) => {
  await page.goto('/design');
  let release!: () => void, committed!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  const finished = new Promise<void>(resolve => { committed = resolve; });
  let original: { sessionId: string; expectedVersion: number; idempotencyKey: string; consent: true; policyVersion: string };
  await page.route('**/api/saved-designs', async route => {
    original = route.request().postDataJSON();
    const response = await route.fetch(); expect(response.status()).toBe(200); committed(); await hold;
    await route.fulfill({ response });
  }, { times: 1 });
  try {
    await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
    await page.getByRole('button', { name: 'Save Design', exact: true }).click();
    await finished;
    const owner = await page.evaluate(body => {
      const key = Object.keys(localStorage).find(key => key.startsWith('sb-') && key.endsWith('-auth-token'))!;
      const owner = JSON.parse(localStorage.getItem(key)!).user.id as string;
      localStorage.setItem(`furnitureos.saved.pending.${owner}`, JSON.stringify({ version: 1, at: Date.now(), body: { ...body, idempotencyKey: 'another-tab-operation' } }));
      return owner;
    }, original!);
    release();
    await expect(page.getByRole('link', { name: 'Open saved Design' })).toBeVisible();
    expect(await page.evaluate(owner => JSON.parse(localStorage.getItem(`furnitureos.saved.pending.${owner}`)!).body.idempotencyKey as string, owner)).toBe('another-tab-operation');
  } finally { release(); }
});

test('switching the selected Design while anonymous sign-in is delayed cancels that Save', async ({ page }) => {
  await page.goto('/design');
  let release!: () => void, started!: () => void, delivered!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { started = resolve; });
  const released = new Promise<void>(resolve => { delivered = resolve; });
  let posts = 0;
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/saved-designs' && request.method() === 'POST') posts++; });
  await page.route('https://local-saved.invalid/auth/v1/signup', async route => {
    const response = await route.fetch({ url: 'http://127.0.0.1:55469/auth/v1/signup' }); started(); await hold;
    try { await route.fulfill({ response }); } catch { /* The old SDK request was cancelled. */ } finally { delivered(); }
  }, { times: 1 });
  try {
    await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
    await page.getByRole('button', { name: 'Save Design', exact: true }).click();
    await requested;
    await page.getByRole('button', { name: 'Dresser centred on the south wall centred on', exact: true }).click();
    release();
    await released;
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
    expect(await page.evaluate(()=>localStorage.getItem('sb-local-saved-auth-token'))).toBeNull();
    await page.goto('/saved');
    await expect(page.getByRole('heading',{name:'Saved Designs',exact:true})).toBeVisible();
    await expect(page.locator('.saved-list li')).toHaveCount(0);
    expect(posts).toBe(0);
    await expect(page.getByRole('button', { name: 'Recover pending save' })).toHaveCount(0);
  } finally { release(); }
});

test('concurrent responses for one list cursor append its page only once', async ({ page, request }) => {
  await page.goto('/design');
  const controls = page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version', '1');
  const sessionId = (await controls.getAttribute('data-session-id'))!;
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open saved Design' })).toBeVisible();
  const token = await page.evaluate(() => {
    const key = Object.keys(localStorage).find(key => key.startsWith('sb-') && key.endsWith('-auth-token'))!;
    return JSON.parse(localStorage.getItem(key)!).access_token as string;
  });
  for (let index = 0; index < 25; index++) {
    const response = await request.post('/api/saved-designs', { headers: { Authorization: `Bearer ${token}` }, data: {
      sessionId, expectedVersion: 1, idempotencyKey: `pagination-seed-${index}`, consent: true,
    } });
    expect(response.status()).toBe(200);
  }
  await page.goto('/saved');
  await expect(page.locator('.saved-list li')).toHaveCount(25);
  let release!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  let requested = 0, delivered = 0;
  page.on('response', response => {
    if (new URL(response.url()).searchParams.has('cursor')) void response.finished().then(() => { delivered++; });
  });
  await page.route('**/api/saved-designs?cursor=*', async route => {
    requested++; const response = await route.fetch(); await hold; await route.fulfill({ response });
  });
  try {
    await page.getByRole('button', { name: 'Load more saved Designs' }).dblclick();
    await expect.poll(() => requested).toBe(2); release();
    await expect.poll(() => delivered).toBe(2);
    await expect(page.locator('.saved-list li')).toHaveCount(26);
    const links = await page.locator('.saved-list li > a').evaluateAll(links => links.map(link => link.getAttribute('href')));
    expect(new Set(links).size).toBe(26);
    await expect(page.getByRole('button', { name: 'Load more saved Designs' })).toHaveCount(0);
  } finally { release(); }
});

test('owner switching during delayed anonymous sign-in cancels the initial Save',async({page,request})=>{
  await page.goto('/design');
  let release!:()=>void,started!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});
  const requested=new Promise<void>(resolve=>{started=resolve;});
  let posts=0;
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/saved-designs'&&request.method()==='POST')posts++;});
  await page.route('https://local-saved.invalid/auth/v1/signup',async route=>{
    const response=await route.fetch({url:'http://127.0.0.1:55469/auth/v1/signup'});started();await held;
    await route.fulfill({response});
  },{times:1});
  try {
    await page.getByRole('checkbox',{name:'I agree to retain this Design'}).check();
    await page.getByRole('button',{name:'Save Design',exact:true}).click();await requested;
    const next=await(await request.post('http://127.0.0.1:55469/auth/v1/signup',{data:{}})).json() as Session;
    await switchOwner(page,next);release();
    await expect(page.locator('.saved-controls [role=status]')).toContainText('account changed');
    expect(posts).toBe(0);
    expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('sb-local-saved-auth-token')!).user.id as string)).toBe(next.user.id);
    const listed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/saved-designs'&&response.request().method()==='GET');
    await page.goto('/saved');await listed;
    await expect(page.locator('.saved-list li')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Recover pending save'})).toHaveCount(0);
  } finally {release();}
});

test('owner switching discards a delayed committed Save response and old recovery hints',async({page,request})=>{
  await page.goto('/design');
  let release!:()=>void,committed!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});
  const finished=new Promise<void>(resolve=>{committed=resolve;});
  let oldId='',oldToken='',oldOwner='';
  await page.route('**/api/saved-designs',async route=>{
    oldToken=route.request().headers().authorization!;
    const response=await route.fetch();expect(response.status()).toBe(200);
    oldId=(await response.json()).id;committed();await held;
    await route.fulfill({response}).catch(()=>{/* The obsolete owner request is aborted. */});
  },{times:1});
  try {
    await page.getByRole('checkbox',{name:'I agree to retain this Design'}).check();
    await page.getByRole('button',{name:'Save Design',exact:true}).click();await finished;
    oldOwner=await page.evaluate(()=>{
      const key=Object.keys(localStorage).find(key=>key.startsWith('sb-')&&key.endsWith('-auth-token'))!;
      const owner=JSON.parse(localStorage.getItem(key)!).user.id as string;
      localStorage.setItem(`furnitureos.capture.${owner}`,'old-capture-pointer');return owner;
    });
    const next=await(await request.post('http://127.0.0.1:55469/auth/v1/signup',{data:{}})).json() as Session;
    await switchOwner(page,next);
    await expect(page.getByRole('button',{name:'Save Design',exact:true})).toBeEnabled();release();
    await expect(page.getByRole('link',{name:'Open saved Design'})).toHaveCount(0);
    expect(await page.evaluate(owner=>[localStorage.getItem(`furnitureos.capture.${owner}`),localStorage.getItem(`furnitureos.saved.pending.${owner}`)],oldOwner)).toEqual([null,null]);
    const listed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/saved-designs'&&response.request().method()==='GET');
    await page.goto('/saved');await listed;
    await expect(page.locator('.saved-list li')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Recover pending save'})).toHaveCount(0);
    const original=await request.get(`/api/saved-designs/${oldId}`,{headers:{Authorization:oldToken}});
    expect(original.status()).toBe(200);
  } finally {release();}
});

test('unusable optional account credentials do not block public preview mutations',async({page,request})=>{
  const session=await(await request.post('http://127.0.0.1:55469/auth/v1/signup',{data:{}})).json() as Session;
  delete (session.user as {is_anonymous?:boolean}).is_anonymous;
  await page.addInitScript(session=>localStorage.setItem('sb-local-saved-auth-token',JSON.stringify(session)),session);
  await page.goto('/design');
  const controls=page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version','1');
  await page.getByRole('button',{name:'Check compatible Products',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Compatible Product'})).toBeVisible();
  await page.getByRole('button',{name:'Swap Product',exact:true}).click();
  await expect(controls).toHaveAttribute('data-version','2');
  expect((await request.post('/api/captures',{data:{consent:true}})).status()).toBe(401);
  expect((await request.get('/api/saved-designs')).status()).toBe(401);
});
