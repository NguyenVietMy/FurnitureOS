import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const evidence = process.env.CURATOR_EVIDENCE_DIR!;
mkdirSync(evidence, { recursive: true });
const mode = async (request: APIRequestContext, value: string) => expect((await request.post('/__controlled/mode', { data: { mode: value } })).ok()).toBe(true);
const rendered = async (page: Page) => {
  await page.waitForFunction(() => window.__furnitureos?.usefulView.status === 'complete', undefined, { timeout: 60_000 });
  const proof = await page.evaluate(() => JSON.parse(JSON.stringify(window.__furnitureos)));
  expect(proof.errors).toEqual([]);
  expect(proof.usefulView.materialsReady && proof.usefulView.texturesReady).toBe(true);
  expect(proof.textures.requested).toBeGreaterThan(0);
  expect(Object.values(proof.instances).every((i: any) => i.actualFrameRendered && i.screenVisible && i.activeMeshCount > 0)).toBe(true);
  return proof;
};

for (const roomType of ['living-room', 'bedroom'] as const) test(`held real HTTP ${roomType} response announces the selected Room Type before delivery`, async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mode(request, 'normal');
  const roomLabel = roomType === 'living-room' ? 'living room' : 'bedroom';
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let release!: () => void;
  let markResponseReady!: () => void;
  const holdResponse = new Promise<void>(resolve => { release = resolve; });
  const responseReady = new Promise<void>(resolve => { markResponseReady = resolve; });
  let requestBody: unknown;
  let result: any;
  await page.route('**/api/live-design/generate', async route => {
    requestBody = route.request().postDataJSON();
    // Run the actual local HTTP authority; only delivery to the UI is held.
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    result = await response.json();
    markResponseReady();
    await holdResponse;
    await route.fulfill({ response });
  });
  try {
    await page.goto('/design/live');
    await expect(page.getByRole('button', { name: 'Generate Design', exact: true })).toBeDisabled();
    await expect(page.getByRole('radio', { name: 'Bedroom', exact: true })).not.toBeChecked();
    await expect(page.getByRole('radio', { name: 'Living room', exact: true })).not.toBeChecked();
    await page.getByRole('radio', { name: roomType === 'living-room' ? 'Living room' : 'Bedroom', exact: true }).check();
    await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
    const delivered = page.waitForResponse(response => response.url().endsWith('/api/live-design/generate'));
    await page.getByRole('button', { name: `Generate ${roomLabel}`, exact: true }).click();
    await responseReady;
    expect(requestBody).toEqual({ roomType, referenceId: 'ref-01' });
    expect(result.roomType).toBe(roomType);
    const loading = page.getByTestId('live-loading');
    await expect(loading).toHaveAttribute('role', 'status');
    await expect(loading.locator('strong')).toHaveText(`Creating your ${roomLabel} Design…`);
    await expect(page.getByRole('button', { name: 'Generating…', exact: true })).toBeDisabled();
    await expect(page.getByTestId('room-canvas')).toHaveCount(0);
    const loadingText = await loading.innerText();
    await page.screenshot({ path: path.join(evidence, `held-${roomType}-loading.png`), fullPage: true });
    release();
    expect((await (await delivered).json()).generationId).toBe(result.generationId);
    await expect(loading).toHaveCount(0);
    let proof = null;
    if (roomType === 'living-room') {
      expect(result.status).toBe('solved');
      proof = await rendered(page);
      expect(Object.keys(proof.instances).sort()).toEqual(['anchor-chair', 'anchor-sofa', 'anchor-table']);
    } else {
      // This provider's fixed bed intent conflicts with the Bedroom door.
      // Keep the authority's typed failure rather than fabricating a success.
      expect(result.status).toBe('failed');
      expect(result.code).toBe('no-valid-design');
      await expect(page.getByTestId('live-failure')).toContainText('No bedroom Design fit this Room.');
      await expect(page.getByTestId('room-canvas')).toHaveCount(0);
    }
    expect(errors).toEqual([]);
    writeFileSync(path.join(evidence, `held-${roomType}.json`), JSON.stringify({ kind: 'CONTROLLED-NO-PAID-TRANSPORT', requestBody, loadingText, result, proof, errors }, null, 2));
    await page.screenshot({ path: path.join(evidence, `held-${roomType}-${result.status}.png`), fullPage: true });
  } finally {
    release();
  }
});

for (const width of [1440, 768, 390]) test(`real HTTP controlled living Design draws normalized new Meshes at ${width}`, async ({ page, request }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  await mode(request, 'normal');
  const errors: string[] = [], assets: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => { if (/\.(ktx2|gltf|bin)(?:$|\?)/.test(r.url())) assets.push(r.url()); });
  await page.goto('/design/live');
  const generate = page.getByRole('button', { name: 'Generate Design', exact: true });
  await expect(generate).toBeDisabled();
  await page.getByRole('radio', { name: 'Living room', exact: true }).check();
  await expect(page.getByRole('button', { name: 'Generate living room', exact: true })).toBeDisabled();
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  const pending = page.waitForResponse(r => r.url().endsWith('/api/live-design/generate'));
  await page.getByRole('button', { name: 'Generate living room', exact: true }).click();
  const response = await pending, result = await response.json();
  expect(response.request().postDataJSON()).toEqual({ roomType: 'living-room', referenceId: 'ref-01' });
  expect(result.status).toBe('solved'); expect(result.roomType).toBe('living-room');
  expect(result.design.circulation.status).toBe('clear');
  expect(result.design.placements.map((p: any) => p.instanceId).sort()).toEqual(['anchor-chair','anchor-sofa','anchor-table']);
  expect(result.design.placements.every((p: any) => p.wallContacts.length === 0)).toBe(true);
  for (let i = 0; i < result.design.placements.length; i++) {
    const p = result.design.placements[i], d = result.design.products[i].dimensionsM;
    expect(p.position[0] - d.widthM / 2).toBeGreaterThan(-3.5);
    expect(p.position[0] + d.widthM / 2).toBeLessThan(3.5);
    expect(p.position[2] - d.depthM / 2).toBeGreaterThan(-3);
    expect(p.position[2] + d.depthM / 2).toBeLessThan(3);
  }
  const proof = await rendered(page);
  expect(Object.keys(proof.instances).sort()).toEqual(['anchor-chair','anchor-sofa','anchor-table']);
  for (const placement of result.design.placements) {
    const instance = proof.instances[placement.instanceId];
    expect(instance.publishedPlacement.position).toEqual(placement.position);
    expect(instance.renderedTransform.position).toEqual(placement.position);
    expect(instance.renderedTransform.yaw).toBe(placement.yaw);
  }
  await expect(page.getByRole('region', { name: 'Product sources and availability' })).toContainText('Purchase availability was not verified');
  await expect(page.getByRole('region', { name: 'Seating Zones', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Seating Zones', exact: true })).toContainText('m wide');
  expect(assets.some(p => p.endsWith('.ktx2'))).toBe(true);
  expect(assets.some(p => p.includes('sofa-stone-beam-westport-linen/lod'))).toBe(true);
  expect(assets.some(p => p.includes('table-rivet-industrial-walnut/lod'))).toBe(true);
  expect(assets.some(p => p.includes('chair-rivet-slade-swivel-graphite/lod'))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  writeFileSync(path.join(evidence, `living-${width}.json`), JSON.stringify({ kind: 'CONTROLLED-NOT-OWNER', result, proof, assets, errors }, null, 2));
  await page.screenshot({ path: path.join(evidence, `living-${width}.png`), fullPage: true });
});

test('second real sofa/table pair, wall group, typed failures and late response clearing', async ({ page, request }) => {
  await mode(request, 'alternate');
  await page.goto('/design/live');
  await page.getByRole('radio', { name: 'Living room', exact: true }).check();
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  const submit = async () => {
    const wait = page.waitForResponse(r => r.url().endsWith('/api/live-design/generate'));
    await page.getByRole('button', { name: 'Generate living room', exact: true }).click();
    return (await wait).json();
  };
  const alternate = await submit(); expect(alternate.status).toBe('solved');
  expect(alternate.design.products.map((p: any) => p.id)).toEqual(['sofa-stone-beam-hillman-ivory', 'table-rivet-modern-pine', 'chair-rivet-slade-swivel-graphite']);
  const proof = await rendered(page);
  writeFileSync(path.join(evidence, 'living-alternate.json'), JSON.stringify({ alternate, proof }, null, 2));
  await page.screenshot({ path: path.join(evidence, 'living-alternate.png'), fullPage: true });
  await mode(request, 'wall'); const wall = await submit();
  writeFileSync(path.join(evidence, 'living-wall.json'), JSON.stringify(wall, null, 2));
  expect(wall.status, JSON.stringify(wall)).toBe('solved');
  expect(wall.design.placements[0].wallContact.wallId).toBe('wall-north'); await rendered(page);
  await page.screenshot({ path: path.join(evidence, 'living-wall.png'), fullPage: true });
  for (const [value, code] of [['no-fit', 'no-valid-design'], ['malformed', 'selection-correction-exhausted']]) {
    await mode(request, value!); const result = await submit(); expect(result.code).toBe(code);
    expect(result.providerCalls).toBe(3); await expect(page.getByTestId('room-canvas')).toHaveCount(0);
    writeFileSync(path.join(evidence, `living-${value}.json`), JSON.stringify(result, null, 2));
  }
  await page.getByRole('radio', { name: 'Light wood and simple lines' }).check();
  const unavailable = await submit(); expect(unavailable.code).toBe('eligible-catalogue-error'); expect(unavailable.providerCalls).toBe(0);
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  await mode(request, 'delay');
  const wait = page.waitForRequest(r => r.url().endsWith('/api/live-design/generate'));
  await page.getByRole('button', { name: 'Generate living room', exact: true }).click(); await wait;
  await page.getByRole('radio', { name: 'Bedroom', exact: true }).check();
  await page.waitForTimeout(2400);
  await expect(page.getByTestId('live-idle')).toBeVisible(); await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await mode(request, 'normal');
});

const A = { Authorization: 'Bearer test-owner-a' };
for (const topology of ['rectangle', 'L-shaped']) test(`Capture ${topology} uses actual Python persisted Living room authority`, async ({ page, request }) => {
  await mode(request, 'normal');
  const calls: any[] = [];
  const post = async (url: string, data: any) => { const r = await request.post(url, { data, headers: A }); expect(r.ok(), await r.text()).toBe(true); return r.json(); };
  let c = await post('/api/captures', { consent: true });
  const patch = async (draft: any) => { const r = await request.patch(`/api/captures/${c.id}/draft`, { data: { expectedRevision: c.revision, draft }, headers: A }); expect(r.ok()).toBe(true); c = await r.json(); };
  await patch({ ...c.draft, topology, roomType: 'living-room' });
  const walls = topology === 'rectangle' ? ['wall-north', 'wall-east', 'wall-south', 'wall-west'] : ['wall-north', 'wall-notch-vertical', 'wall-notch-horizontal', 'wall-east', 'wall-south', 'wall-west'];
  for (let i = 0; i < walls.length; i++) {
    const image = execFileSync(path.resolve('.venv/Scripts/python.exe'), ['-c', 'import sys;from backend_tests.test_captures import png;sys.stdout.buffer.write(png(int(sys.argv[1])))', String(i)]);
    c = await post(`/api/captures/${c.id}/photos`, { expectedRevision: c.revision, primaryWallId: walls[i], declaredBytes: image.length });
    const r = await request.post(`/api/captures/${c.id}/photos/${c.photos.at(-1).id}/content?expectedRevision=${c.revision}`, { data: image, headers: { ...A, 'Content-Type': 'image/png' } });
    expect(r.ok()).toBe(true); c = await r.json();
  }
  await patch({ ...c.draft, widthM: 8, depthM: 8, heightM: 2.7, ...(topology === 'L-shaped' ? { notchWidthM: 2, notchDepthM: 2 } : {}), dimensionsConfirmed: true, wallReviews: walls, furnitureAcknowledged: true });
  await patch({ ...c.draft, dimensionsConfirmed: true, wallReviews: walls });
  const confirmed = await post(`/api/captures/${c.id}/confirm`, { expectedRevision: c.revision }); expect(confirmed.status).toBe('confirmed'); c = confirmed.capture;
  const owner = '11111111-1111-1111-1111-111111111111';
  const session = { access_token: 'test-owner-a', token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: 'CONTROLLED', user: { id: owner, aud: 'authenticated', role: 'authenticated', is_anonymous: true, created_at: new Date().toISOString() } };
  await page.addInitScript(({ session, owner, id }) => { localStorage.setItem('sb-capture-test-auth-token', JSON.stringify(session)); localStorage.setItem(`furnitureos.capture.${owner}`, id); }, { session, owner, id: c.id });
  await page.route('https://capture-test.invalid/auth/v1/**', route => route.fulfill({ json: route.request().url().endsWith('/user') ? session.user : session }));
  await page.goto('/capture');
  await expect(page.getByRole('radio', { name: 'Living room', exact: true })).toBeChecked();
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  const pending = page.waitForResponse(r => r.url().endsWith(`/api/captures/${c.id}/generate`));
  await page.getByRole('button', { name: 'Generate confirmed Room', exact: true }).click();
  const result = await (await pending).json(); expect(result.result.status).toBe('solved'); expect(result.result.roomType).toBe('living-room');
  expect(result.result.design.placements.map((p: any) => p.instanceId).sort()).toEqual(['anchor-chair','anchor-sofa','anchor-table']);
  expect(result.result.design.room).toEqual(c.room); const proof = await rendered(page);
  expect(Object.keys(proof.instances).sort()).toEqual(['anchor-chair','anchor-sofa','anchor-table']);
  await page.screenshot({ path: path.join(evidence, `living-capture-${topology}.png`), fullPage: true });
  writeFileSync(path.join(evidence, `living-capture-${topology}.json`), JSON.stringify({ kind: 'SYNTHETIC-CONTROLLED-NOT-OWNER', capture: c, result, proof }, null, 2));
  const sid = result.result.design.swap.sessionId;
  await page.getByRole('radio', { name: 'Bedroom', exact: true }).check(); await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  expect((await (await request.get(`/api/swaps/${sid}`, { headers: A })).json()).status).toBe('unknown-session');
});
