import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const root = fileURLToPath(new URL('..', import.meta.url));
const productId = 'bed-prudence-tufted-queen-natural';
const manifest = JSON.parse(readFileSync(join(root, 'public', 'products', productId, 'asset-manifest.json'), 'utf8')) as { source: { url: string; bounds: { size: number[] } }; normalization: { frontAxis: string } };
const shots = process.env.FURNITUREOS_EVIDENCE_DIR ?? join(root, 'test-results', 'screenshots'); mkdirSync(shots, { recursive: true });
interface SceneInstance { instanceId: string; productId: string; ready: boolean; worldBounds: { min: number[]; max: number[]; size: number[] } | null; publishedPlacement: { position: number[]; yaw: number; wallId: string | null }; renderedTransform: { position: number[]; yaw: number; matrixWorld: number[] } | null; meshCount: number; }
interface Scene { ready: boolean; productId: string; activeLod: number; framesRendered: number; worldBounds: { min: number[]; max: number[]; size: number[] } | null; placement: { wallId: string | null } | null; products?: Record<string, { ready: boolean; placement: { position: number[]; yaw: number; wallId: string | null } }>; instances?: Record<string, SceneInstance>; textures: { requested: number; decoded: number; fallback: number }; camera: number[] | null; }
interface SolvedPayload {
  status: 'solved';
  products: Array<{ id: string; category: string; placementClass: string; dimensionsM: { widthM: number; heightM: number; depthM: number }; mesh: { boundsM: { min: number[]; max: number[] } } }>;
  placements: Array<{ instanceId: string; productId: string; position: number[]; yaw: number; wallContact: { wallId: string } | null }>;
}
const scene = (page: Page) => page.evaluate(() => JSON.parse(JSON.stringify(window.__furnitureos)) as Scene);
async function waitForProduct(page: Page) { await page.waitForFunction(() => window.__furnitureos?.ready && (window.__furnitureos.framesRendered ?? 0) > 3, undefined, { timeout: 60_000 }); }
async function expectDefaultCamera(page: Page) {
  const camera = (await scene(page)).camera;
  expect(camera).not.toBeNull();
  for (const [index, expected] of [3.1, 2.3, 3.7].entries()) {
    expect(camera![index]).toBeCloseTo(expected, 4);
  }
}
async function expectNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client);
}

async function expectSingleDesignHeading(page: Page) {
  await expect(page.locator('h1')).toHaveCount(1);
  await expect(page.locator('h1')).toHaveText('Preview furniture around the bedroom');
}

async function centreCameraAtDistance(page: Page, distance: number) {
  const canvas = (await page.locator('canvas').boundingBox())!;
  await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2);
  await page.mouse.down();
  await page.mouse.move(canvas.x + canvas.width / 2 + 105, canvas.y + canvas.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect.poll(async () => Math.abs((await scene(page)).camera?.[0] ?? 10)).toBeLessThan(0.8);
  await page.evaluate((metres) => window.__furnitureos?.setCameraDistanceM?.(metres), distance);
  await expect.poll(async () => {
    const camera = (await scene(page)).camera;
    return camera ? Math.round(Math.hypot(camera[0]!, camera[1]! - 0.7, camera[2]!) * 10) / 10 : null;
  }).toBe(distance);
}

function expectedWorldBounds(
  bounds: { min: number[]; max: number[] },
  placement: { position: number[]; yaw: number },
) {
  const cosine = Math.cos(placement.yaw);
  const sine = Math.sin(placement.yaw);
  const corners = [bounds.min[0]!, bounds.max[0]!].flatMap((x) =>
    [bounds.min[1]!, bounds.max[1]!].flatMap((y) =>
      [bounds.min[2]!, bounds.max[2]!].map((z) => [
        placement.position[0]! + x * cosine + z * sine,
        placement.position[1]! + y,
        placement.position[2]! - x * sine + z * cosine,
      ]),
    ),
  );
  const min = [0, 1, 2].map((axis) => Math.min(...corners.map((corner) => corner[axis]!)));
  const max = [0, 1, 2].map((axis) => Math.max(...corners.map((corner) => corner[axis]!)));
  return { min, max, size: max.map((value, axis) => value - min[axis]!) };
}

async function expectRenderedPayload(page: Page, payload: SolvedPayload) {
  const ids = payload.placements.map(({ instanceId }) => instanceId);
  await page.waitForFunction(
    (instanceIds) => instanceIds.every((id) => window.__furnitureos?.instances?.[id]?.ready),
    ids,
    { timeout: 60_000 },
  );
  const rendered = await scene(page);
  for (const [index, placement] of payload.placements.entries()) {
    const product = payload.products[index]!;
    const actual = rendered.instances?.[placement.instanceId];
    const expectedBounds = expectedWorldBounds(product.mesh.boundsM, placement);
    expect(actual?.instanceId).toBe(placement.instanceId);
    expect(actual?.productId).toBe(placement.productId);
    expect(actual?.publishedPlacement.position).toEqual(placement.position);
    expect(actual?.publishedPlacement.yaw).toBe(placement.yaw);
    expect(actual?.renderedTransform?.position).toEqual(placement.position);
    expect(actual?.renderedTransform?.yaw).toBe(placement.yaw);
    expect(actual?.renderedTransform?.matrixWorld).toHaveLength(16);
    expect(actual?.meshCount).toBeGreaterThan(0);
    for (const key of ['min', 'max', 'size'] as const) {
      for (const axis of [0, 1, 2]) {
        expect(actual?.worldBounds?.[key][axis]).toBeCloseTo(expectedBounds[key][axis]!, 4);
      }
    }
  }
  return rendered;
}

test('keeps one page heading and a discoverable subordinate hierarchy in every Design result state', async ({ page }) => {
  await page.goto('/design');
  await waitForProduct(page);
  await expectSingleDesignHeading(page);
  await expect(page.locator('.product-facts > .panel-head > h2')).toHaveText(['Prudence Tufted Queen Bed']);
  await expect(page.locator('.product-facts section > h3')).toHaveText([
    'Dimensions',
    'Placement',
    'Mesh',
    'Availability',
    'Attribution',
  ]);

  await page.getByTestId('fixture-matching-nightstands').click();
  await waitForProduct(page);
  await expectSingleDesignHeading(page);
  await expect(page.locator('.product-facts > .panel-head > h2')).toHaveText([
    'Hayes One-Drawer Nightstand',
    'Hayes One-Drawer Nightstand',
  ]);
  await expect(page.locator('.product-facts section > h3')).toHaveCount(10);

  await page.getByTestId('fixture-door-swing-failure').click();
  await expect(page.getByTestId('design-failure')).toBeVisible();
  await expectSingleDesignHeading(page);
  await expect(page.locator('.product-facts > .panel-head > h2')).toHaveCount(0);
  await expect(page.getByTestId('design-failure').locator('h2')).toContainText('door-swing-exclusion');
});

test('renders FastAPI data with the real Product, attribution, orbit, LODs and same-origin assets', async ({ page }) => {
  const apiResponses: string[] = []; const responses: { url: string; status: number }[] = [];
  page.on('response', (response) => { responses.push({ url: response.url(), status: response.status() }); if (response.url().includes('/api/design-resolution')) apiResponses.push(response.url()); });
  await page.goto('/design'); await expect(page.getByTestId('api-preview')).toBeVisible(); await waitForProduct(page);
  expect(apiResponses.length).toBeGreaterThan(0); await expect(page.getByTestId('design-panel')).toContainText('Prudence Tufted Queen Bed'); await expect(page.getByTestId('fit-status')).toHaveAttribute('data-fit', 'fits'); await expect(page.getByTestId('dimensions')).toContainText(`front ${manifest.normalization.frontAxis}`);
  const initial = await scene(page); expect(initial.productId).toBe(productId); expect(initial.placement?.wallId).toBe('wall-north'); expect(initial.textures.decoded).toBeGreaterThan(0); for (let axis = 0; axis < 3; axis += 1) expect(Math.abs(initial.worldBounds!.size[axis]! - manifest.source.bounds.size[axis]!)).toBeLessThan(0.02); expect(Math.abs(initial.worldBounds!.min[1]!)).toBeLessThan(0.01); expect(Math.abs(initial.worldBounds!.min[2]! + 1.5)).toBeLessThan(0.01);
  const expectLevelAt = async (distance: number, activeLod: number) => {
    await page.evaluate((metres) => window.__furnitureos?.setCameraDistanceM?.(metres), distance);
    await expect.poll(async () => {
      const current = await scene(page);
      const camera = current.camera;
      return {
        activeLod: current.activeLod,
        cameraDistanceM: camera
          ? Math.round(Math.hypot(camera[0]!, camera[1]! - 0.7, camera[2]!) * 1000) / 1000
          : null,
      };
    }, { timeout: 30_000 }).toEqual({ activeLod, cameraDistanceM: distance });
  };
  await expectLevelAt(3, 0); await expectLevelAt(7, 1); await expectLevelAt(12, 2);
  const cameraBefore = (await scene(page)).camera!; const box = (await page.locator('canvas').boundingBox())!; await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 - 220, box.y + box.height / 2 - 40, { steps: 12 }); await page.mouse.up(); await page.waitForFunction((before) => { const camera = window.__furnitureos?.camera; return !!camera && Math.hypot(camera[0]! - before[0]!, camera[2]! - before[2]!) > 0.5; }, cameraBefore); await page.screenshot({ path: join(shots, 'room-orbited-view.png') });
  for (const response of responses.filter((item) => item.url.includes('/decoders/basis/') || item.url.endsWith('.ktx2') || /\/lod\d\.gltf$/.test(item.url))) expect(response.status).toBe(200);
  await expect(page.getByTestId('attribution-source')).toHaveAttribute('href', 'https://amazon-berkeley-objects.s3.amazonaws.com/index.html'); await expect(page.getByTestId('attribution-license')).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/4.0/'); await expect(page.getByTestId('attribution-material')).toHaveAttribute('href', manifest.source.url); await page.screenshot({ path: join(shots, 'room-default-view.png') });
});

test('keeps the Product visible with missing textures and recovers after the FastAPI backend returns', async ({ page }) => {
  await page.route('**/*.ktx2', (route) => route.abort()); await page.goto('/design'); await waitForProduct(page); const fallback = await scene(page); expect(fallback.textures.requested).toBeGreaterThan(0); expect(fallback.textures.fallback).toBe(fallback.textures.requested); expect(fallback.worldBounds).not.toBeNull(); expect(fallback.placement?.wallId).toBe('wall-north'); await page.screenshot({ path: join(shots, 'room-missing-textures.png') });
  await page.unroute('**/*.ktx2'); await page.route('**/api/design-resolution', (route) => route.abort()); await page.reload(); await expect(page.getByTestId('api-error')).toContainText('Design data is unavailable'); const retry = page.getByRole('button', { name: 'Retry' }); await expect(retry).toBeVisible(); await page.unroute('**/api/design-resolution'); await retry.click(); await expect(page.getByTestId('api-preview')).toBeVisible(); await waitForProduct(page); await expect(page.getByTestId('design-panel')).toContainText('Prudence Tufted Queen Bed');
});

test('preserves viewport-contained desktop framing and the accepted stacked mobile flow', async ({ page }) => {
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/design');
    await waitForProduct(page);
    await expectDefaultCamera(page);
    await expectNoHorizontalOverflow(page);

    const layout = (await page.getByTestId('api-preview').boundingBox())!;
    const stage = (await page.getByTestId('stage').boundingBox())!;
    const canvas = (await page.getByTestId('room-canvas').boundingBox())!;
    const panel = page.getByTestId('design-panel');
    const panelBox = (await panel.boundingBox())!;
    const pageScrollBefore = await page.evaluate(() => window.scrollY);

    expect(layout.y).toBe(0);
    expect(layout.height).toBeCloseTo(viewport.height, 0);
    expect(stage.y).toBeGreaterThanOrEqual(0);
    expect(stage.y + stage.height).toBeLessThanOrEqual(viewport.height);
    expect(canvas.y).toBeGreaterThanOrEqual(0);
    expect(canvas.y + canvas.height).toBeLessThanOrEqual(viewport.height);
    expect(panelBox.y + panelBox.height).toBeLessThanOrEqual(viewport.height);
    expect(canvas.height).toBeGreaterThan(viewport.height * 0.7);
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(viewport.height);

    await page.screenshot({ path: join(shots, `room-layout-${viewport.width}x${viewport.height}-default.png`) });

    const panelScroll = await panel.evaluate((element) => {
      const before = element.scrollTop;
      element.scrollTop = element.scrollHeight;
      return { before, clientHeight: element.clientHeight, scrollHeight: element.scrollHeight };
    });
    expect(panelScroll.before).toBe(0);
    expect(panelScroll.scrollHeight).toBeGreaterThan(panelScroll.clientHeight);
    await expect.poll(() => panel.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    await expect(page.getByTestId('attribution-material')).toBeInViewport();
    await page.getByTestId('attribution-material').focus();
    await expect(page.getByTestId('attribution-material')).toBeFocused();

    const canvasAfter = (await page.getByTestId('room-canvas').boundingBox())!;
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScrollBefore);
    expect(canvasAfter.x).toBeCloseTo(canvas.x, 1);
    expect(canvasAfter.y).toBeCloseTo(canvas.y, 1);
    expect(canvasAfter.width).toBeCloseTo(canvas.width, 1);
    expect(canvasAfter.height).toBeCloseTo(canvas.height, 1);
  }

  for (const viewport of [{ width: 390, height: 844 }, { width: 768, height: 1024 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/design');
    await waitForProduct(page);
    await expectDefaultCamera(page);
    await expectNoHorizontalOverflow(page);

    const stage = (await page.getByTestId('stage').boundingBox())!;
    const canvas = (await page.getByTestId('room-canvas').boundingBox())!;
    const panel = page.getByTestId('design-panel');
    const panelOverflow = await panel.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }));
    expect(stage.y).toBeGreaterThanOrEqual(0);
    expect(stage.y + stage.height).toBeLessThanOrEqual(viewport.height);
    expect(canvas.width).toBeGreaterThan(viewport.width - 50);
    expect(canvas.height).toBeGreaterThan(300);
    expect(panelOverflow.scrollHeight - panelOverflow.clientHeight).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(viewport.height);

    await page.screenshot({ path: join(shots, `room-layout-${viewport.width}x${viewport.height}-default.png`) });

    const pageScrollBefore = await page.evaluate(() => window.scrollY);
    await page.getByTestId('attribution-material').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('attribution-material')).toBeInViewport();
    await page.getByTestId('attribution-material').focus();
    await expect(page.getByTestId('attribution-material')).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(pageScrollBefore);
    expect(await panel.evaluate((element) => element.scrollTop)).toBe(0);
    await expectDefaultCamera(page);
  }
});

test('selects wall-relative fixtures and renders the exact server-returned Placements', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/design');
  await waitForProduct(page);
  await page.screenshot({ path: join(shots, 'ticket-3-against-desktop.png') });

  for (const fixtureId of ['centred-on-wall', 'in-corner']) {
    const responsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
    await page.getByTestId(`fixture-${fixtureId}`).click();
    const payload = await (await responsePromise).json() as {
      status: string;
      products: Array<{ id: string }>;
      placements: Array<{ instanceId: string; productId: string; position: number[]; yaw: number; wallContact: { wallId: string } | null }>;
    };
    expect(payload.status).toBe('solved');
    await waitForProduct(page);
    const rendered = await scene(page);
    for (const placement of payload.placements) {
      const actual = rendered.instances?.[placement.instanceId];
      expect(actual?.ready).toBe(true);
      expect(actual?.publishedPlacement.position).toEqual(placement.position);
      expect(actual?.publishedPlacement.yaw).toBe(placement.yaw);
      expect(actual?.publishedPlacement.wallId).toBe(placement.wallContact?.wallId ?? null);
      expect(actual?.renderedTransform?.position).toEqual(placement.position);
      expect(actual?.renderedTransform?.yaw).toBe(placement.yaw);
      expect(actual?.meshCount).toBeGreaterThan(0);
    }
  }

  const matchingResponse = page.waitForResponse((response) =>
    response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
  await page.getByTestId('fixture-matching-nightstands').click();
  const matching = await (await matchingResponse).json() as {
    status: string;
    products: Array<{ id: string }>;
    placements: Array<{ instanceId: string; productId: string; position: number[]; yaw: number; wallContact: { wallId: string } | null }>;
  };
  expect(matching.status).toBe('solved');
  expect(matching.products.map(({ id }) => id)).toEqual([
    'nightstand-alkove-hayes-wild-oak',
    'nightstand-alkove-hayes-wild-oak',
  ]);
  await waitForProduct(page);
  const matchingScene = await scene(page);
  const renderedInstances = matching.placements.map((placement) => matchingScene.instances?.[placement.instanceId]);
  expect(renderedInstances).toHaveLength(2);
  for (const [index, actual] of renderedInstances.entries()) {
    const placement = matching.placements[index]!;
    expect(actual?.instanceId).toBe(placement.instanceId);
    expect(actual?.productId).toBe(placement.productId);
    expect(actual?.publishedPlacement.position).toEqual(placement.position);
    expect(actual?.renderedTransform?.position).toEqual(placement.position);
    expect(actual?.renderedTransform?.yaw).toBe(placement.yaw);
    expect(actual?.renderedTransform?.matrixWorld).toHaveLength(16);
    expect(actual?.meshCount).toBeGreaterThan(0);
  }
  expect(renderedInstances[0]?.worldBounds).not.toEqual(renderedInstances[1]?.worldBounds);
  writeFileSync(
    join(shots, 'ticket-3-matching-nightstands-scene.json'),
    JSON.stringify({
      placements: matching.placements,
      renderedInstances: Object.fromEntries(matching.placements.map((placement) => [
        placement.instanceId,
        matchingScene.instances?.[placement.instanceId],
      ])),
    }, null, 2),
  );
  await page.screenshot({ path: join(shots, 'ticket-3-matching-nightstands-desktop.png') });

  const cornerResponse = page.waitForResponse((response) =>
    response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
  await page.getByTestId('fixture-in-corner').click();
  await cornerResponse;
  await waitForProduct(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: join(shots, 'ticket-3-in-corner-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.getByTestId('fixture-against-wall').click();
  await waitForProduct(page);
  await page.screenshot({ path: join(shots, 'ticket-3-against-tablet.png'), fullPage: true });

  await page.getByTestId('fixture-door-swing-failure').click();
  await expect(page.getByTestId('design-failure')).toHaveAttribute('data-reason', 'door-swing-exclusion');
  await expect(page.getByTestId('design-failure')).toContainText('bedroom-door');
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await page.screenshot({ path: join(shots, 'ticket-3-door-swing-failure-tablet.png'), fullPage: true });
});

test('renders ticket-4 related Products, floor covering and floor lamp from exact server Placements', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/design');
  await waitForProduct(page);
  const evidence: Record<string, unknown> = {};

  for (const fixtureId of [
    'adjacent-nightstand',
    'facing-chair',
    'flanking-nightstands',
    'rug-under-bed',
    'floor-lamp',
    'relative-chain',
  ]) {
    const responsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
    await page.getByTestId(`fixture-${fixtureId}`).click();
    const payload = await (await responsePromise).json() as SolvedPayload;
    expect(payload.status).toBe('solved');
    const rendered = await expectRenderedPayload(page, payload);
    evidence[fixtureId] = {
      products: payload.products.map(({ id, category, placementClass, mesh }) => ({ id, category, placementClass, boundsM: mesh.boundsM })),
      placements: payload.placements,
      renderedInstances: Object.fromEntries(payload.placements.map(({ instanceId }) => [instanceId, rendered.instances?.[instanceId]])),
    };

    if (fixtureId === 'flanking-nightstands') {
      expect(payload.products.map(({ id }) => id)).toEqual([
        'bed-prudence-tufted-queen-natural',
        'nightstand-alkove-hayes-wild-oak',
        'nightstand-alkove-hayes-wild-oak',
      ]);
      await centreCameraAtDistance(page, 7);
      await page.screenshot({ path: join(shots, 'ticket-4-flanking-desktop.png') });
      await page.reload();
      await waitForProduct(page);
    }
    if (fixtureId === 'rug-under-bed') {
      expect(payload.products[1]?.placementClass).toBe('floor-covering');
      await page.screenshot({ path: join(shots, 'ticket-4-rug-under-bed-desktop.png') });
    }
    if (fixtureId === 'floor-lamp') {
      expect(payload.products[1]?.category).toBe('lamp');
      expect(payload.products[1]?.placementClass).toBe('floor-standing');
      expect(payload.placements[1]?.position[1]).toBe(0);
      expect(rendered.instances?.['standing-lamp']?.worldBounds?.min[1]).toBeCloseTo(0, 4);
    }
  }

  writeFileSync(join(shots, 'ticket-4-object-relative-scene.json'), JSON.stringify(evidence, null, 2));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId('fixture-facing-chair').click();
  await page.waitForFunction(() => window.__furnitureos?.instances?.['chair-facing-bed']?.ready, undefined, { timeout: 60_000 });
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: join(shots, 'ticket-4-facing-mobile.png'), fullPage: true });

  await page.setViewportSize({ width: 768, height: 1024 });
  await page.getByTestId('fixture-floor-lamp').click();
  await page.waitForFunction(() => window.__furnitureos?.instances?.['standing-lamp']?.ready, undefined, { timeout: 60_000 });
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: join(shots, 'ticket-4-floor-lamp-tablet.png'), fullPage: true });
});

test('renders the complete ticket-4 bedroom with every relationship in one Design', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/design');
  await waitForProduct(page);
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
  await page.getByTestId('fixture-complete-bedroom').click();
  const payload = await (await responsePromise).json() as SolvedPayload;
  expect(payload.status).toBe('solved');
  const rendered = await expectRenderedPayload(page, payload);
  expect(payload.placements.map(({ instanceId }) => instanceId)).toEqual([
    'complete-bed',
    'complete-left-nightstand',
    'complete-right-nightstand',
    'complete-chair',
    'complete-rug',
    'complete-lamp',
  ]);

  const placements = Object.fromEntries(payload.placements.map((placement) => [placement.instanceId, placement]));
  const products = Object.fromEntries(payload.placements.map((placement, index) => [placement.instanceId, payload.products[index]!]));
  const bed = placements['complete-bed']!;
  const left = placements['complete-left-nightstand']!;
  const right = placements['complete-right-nightstand']!;
  const chair = placements['complete-chair']!;
  const rugBounds = rendered.instances?.['complete-rug']?.worldBounds;
  const bedBounds = rendered.instances?.['complete-bed']?.worldBounds;
  const lampBounds = rendered.instances?.['complete-lamp']?.worldBounds;
  const bedRear = bed.position[2]! - products['complete-bed']!.dimensionsM.depthM / 2;
  expect(left.position[0]).toBeLessThan(bed.position[0]!);
  expect(right.position[0]).toBeGreaterThan(bed.position[0]!);
  for (const flank of [left, right]) {
    expect(flank.position[2]! - products[flank.instanceId]!.dimensionsM.depthM / 2).toBeCloseTo(bedRear, 5);
  }
  expect(chair.position[2]).toBeGreaterThan(bed.position[2]!);
  expect(chair.yaw).toBeCloseTo(Math.PI, 8);
  expect(products['complete-rug']!.placementClass).toBe('floor-covering');
  expect(Math.min(rugBounds!.max[0]!, bedBounds!.max[0]!) - Math.max(rugBounds!.min[0]!, bedBounds!.min[0]!)).toBeGreaterThan(0);
  expect(Math.min(rugBounds!.max[2]!, bedBounds!.max[2]!) - Math.max(rugBounds!.min[2]!, bedBounds!.min[2]!)).toBeGreaterThan(0);
  expect(products['complete-lamp']!.placementClass).toBe('floor-standing');
  expect(lampBounds?.min[1]).toBeCloseTo(0, 4);
  const lampFacts = page.getByTestId('product-facts-lamp-rivet-harper-brass');
  await expect(lampFacts.getByTestId('required-clearance')).toContainText('none declared');
  await expect(lampFacts.getByTestId('optional-access-guidance')).toContainText('not required for this fit');
  await expect(lampFacts).not.toContainText('Access kept clear');

  writeFileSync(join(shots, 'ticket-4-complete-bedroom-scene.json'), JSON.stringify({
    products: payload.products,
    placements: payload.placements,
    renderedInstances: Object.fromEntries(payload.placements.map(({ instanceId }) => [instanceId, rendered.instances?.[instanceId]])),
  }, null, 2));

  await centreCameraAtDistance(page, 8.5);
  await page.screenshot({ path: join(shots, 'ticket-4-complete-bedroom-desktop.png') });
  for (const viewport of [{ width: 390, height: 844 }, { width: 768, height: 1024 }]) {
    await page.setViewportSize(viewport);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: join(shots, `ticket-4-complete-bedroom-${viewport.width === 390 ? 'mobile' : 'tablet'}.png`) });
  }
});

test('shows ticket-4 object-relative failures without a stale Room canvas', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/design');
  await waitForProduct(page);
  const cases = [
    ['missing-relative-reference', 'unknown-intent-reference'],
    ['relative-cycle', 'cyclic-intent-reference'],
    ['malformed-flanking', 'invalid-flanking-group'],
    ['furniture-negative-gap', 'invalid-relative-gap'],
  ] as const;

  for (const [fixtureId, reason] of cases) {
    await page.getByTestId(`fixture-${fixtureId}`).click();
    await expect(page.getByTestId('design-failure')).toHaveAttribute('data-reason', reason);
    await expect(page.getByTestId('room-canvas')).toHaveCount(0);
    await expectSingleDesignHeading(page);
    await page.screenshot({ path: join(shots, `ticket-4-${fixtureId}-failure.png`) });
  }
});

test('renders the repairable zoned Design and honest exhausted feedback at every evidence viewport', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/design');
  await waitForProduct(page);

  const repairedResponse = page.waitForResponse((response) =>
    response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
  await page.getByTestId('fixture-zoned-repairable').click();
  const repaired = await (await repairedResponse).json() as SolvedPayload & {
    zones: Array<{ id: string; bounds: { minX: number; minZ: number; maxX: number; maxZ: number } }>;
    circulation: { status: string; clearanceWidthM: number; accessRegions: Array<{ id: string }> };
    arrangementHistory: { attempts: Array<{ stage: string; outcome: string; changedRequestIds: string[] }> };
  };
  expect(repaired.status).toBe('solved');
  expect(repaired.zones).toHaveLength(3);
  expect(repaired.circulation.status).toBe('clear');
  expect(repaired.circulation.clearanceWidthM).toBe(0.6);
  expect(repaired.circulation.accessRegions.map(({ id }) => id)).toContain('door:bedroom-south-door');
  expect(repaired.arrangementHistory.attempts.map(({ outcome }) => outcome)).toEqual([
    'circulation-blocked',
    'solved',
  ]);
  expect(repaired.arrangementHistory.attempts[1]?.changedRequestIds).toEqual(['c-barrier-right']);
  expect(repaired.placements.map(({ instanceId }) => instanceId)).toEqual([
    'a-bed',
    'b-barrier-left',
    'c-barrier-right',
    'z-zone-rug',
  ]);
  const repairedScene = await expectRenderedPayload(page, repaired);
  await expect(page.getByTestId('arrangement-feedback')).toContainText('A connected walking route is clear');
  await expect(page.getByTestId('arrangement-feedback')).toContainText('0.60 m clearance');
  await expect(page.getByTestId('arrangement-attempts')).toContainText('Repair selection');
  await expect(page.getByTestId('stage-arrangement-outcome')).toContainText('Walking route clear');
  expect(repairedScene.camera?.[0]).toBeGreaterThan(6);
  expect(repairedScene.camera?.[1]).toBeGreaterThan(8);
  expect(repairedScene.camera?.[2]).toBeLessThan(-8);
  writeFileSync(join(shots, 'ticket-5-repairable-scene.json'), JSON.stringify({
    response: repaired,
    renderedInstances: Object.fromEntries(repaired.placements.map(({ instanceId }) => [
      instanceId,
      repairedScene.instances?.[instanceId],
    ])),
  }, null, 2));

  for (const viewport of [
    { width: 1440, height: 1000, label: 'desktop' },
    { width: 390, height: 844, label: 'mobile' },
    { width: 768, height: 1024, label: 'tablet' },
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByTestId('design-panel').evaluate((panel) => { panel.scrollTop = 0; });
    await expectNoHorizontalOverflow(page);
    await expect(page.getByTestId('stage-arrangement-outcome')).toBeVisible();
    await page.screenshot({ path: join(shots, `ticket-5-repairable-${viewport.label}.png`) });
    if (viewport.label === 'mobile') {
      await page.getByTestId('arrangement-feedback').scrollIntoViewIfNeeded();
      await expect(page.getByTestId('arrangement-feedback')).toBeVisible();
      await page.screenshot({ path: join(shots, `ticket-5-repairable-${viewport.label}-feedback.png`) });
    }
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  const exhaustedResponse = page.waitForResponse((response) =>
    response.url().includes('/api/design-resolution') && response.request().method() === 'POST');
  await page.getByTestId('fixture-zoned-exhausted').click();
  const exhausted = await (await exhaustedResponse).json() as {
    status: 'failed';
    reason: string;
    detail: string;
    zones: Array<{ id: string }>;
    limitingConstraint: {
      code: string;
      disconnectedAccessIds: string[];
      implicatedRequestIds: string[];
      attributionLimited: boolean;
      attributionLimitation: string;
      gridResolutionM: number;
    };
    arrangementHistory: { attempts: Array<{ stage: string; outcome: string; droppedRequestIds: string[] }> };
  };
  expect(exhausted.status).toBe('failed');
  expect(exhausted.reason).toBe('NO_VALID_DESIGN');
  expect(exhausted.limitingConstraint.code).toBe('CIRCULATION_BLOCKED');
  expect(exhausted.limitingConstraint.disconnectedAccessIds.length).toBeGreaterThan(0);
  expect(exhausted.limitingConstraint.implicatedRequestIds).toEqual([...exhausted.limitingConstraint.implicatedRequestIds].sort());
  expect(exhausted.limitingConstraint.attributionLimited).toBe(true);
  expect(exhausted.limitingConstraint.attributionLimitation).toBeTruthy();
  expect(exhausted.limitingConstraint.gridResolutionM).toBe(0.05);
  expect(exhausted.arrangementHistory.attempts.map(({ stage }) => stage)).toEqual([
    'initial',
    'repair',
    'repair',
    'drop',
  ]);
  expect(exhausted.arrangementHistory.attempts.at(-1)?.droppedRequestIds).toEqual(['z-zone-rug']);
  await expect(page.getByTestId('design-failure')).toHaveAttribute('data-reason', 'NO_VALID_DESIGN');
  await expect(page.getByTestId('arrangement-feedback')).toContainText('No traversable arrangement was found');
  await expect(page.getByTestId('attribution-limitation')).toContainText('could not be attributed to one Product');
  await expect(page.getByTestId('stage-invalid-fit')).toContainText('No connected walking route was found');
  await expect(page.getByTestId('stage-invalid-fit').locator('details')).not.toHaveAttribute('open', '');
  await expect(page.getByTestId('stage-invalid-fit').locator('details')).toContainText('CIRCULATION_BLOCKED');
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect(page.locator('.product-facts')).toHaveCount(0);
  writeFileSync(join(shots, 'ticket-5-exhausted-response.json'), JSON.stringify(exhausted, null, 2));

  for (const viewport of [
    { width: 1440, height: 1000, label: 'desktop' },
    { width: 390, height: 844, label: 'mobile' },
    { width: 768, height: 1024, label: 'tablet' },
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByTestId('design-panel').evaluate((panel) => { panel.scrollTop = 0; });
    await expectNoHorizontalOverflow(page);
    await expect(page.getByTestId('room-canvas')).toHaveCount(0);
    await expect(page.getByTestId('stage-invalid-fit')).toBeVisible();
    await page.screenshot({ path: join(shots, `ticket-5-exhausted-${viewport.label}.png`) });
    if (viewport.label === 'mobile') {
      await page.getByTestId('arrangement-feedback').scrollIntoViewIfNeeded();
      await expect(page.getByTestId('arrangement-feedback')).toBeVisible();
      await page.screenshot({ path: join(shots, `ticket-5-exhausted-${viewport.label}-feedback.png`) });
    }
  }

  await page.goto('/');
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect(page.getByText('Interactive concept preview. Illustrative furnishings; no live Catalogue or room generation.').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /catalogue gallery/i })).toHaveCount(0);
});
