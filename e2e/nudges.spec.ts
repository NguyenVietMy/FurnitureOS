import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page, type CDPSession } from '@playwright/test';
import { resultStream } from './variant-events.fixture';

const shots = process.env.FURNITUREOS_EVIDENCE_DIR ?? 'test-results/screenshots';
mkdirSync(shots, { recursive: true });

async function ready(page: Page, instanceId = 'bed-against-north') {
  await page.waitForFunction((id) => window.__furnitureos?.instances[id]?.actualFrameRendered, instanceId, { timeout: 60000 });
  await page.getByRole('combobox', { name: 'Placement to Nudge' }).selectOption(instanceId);
  await page.getByRole('button', { name: /Prepare Nudge|Retry Nudge/ }).click();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'ready');
  await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();
}

async function points(page: Page, instanceId: string) {
  const bounds = await page.getByTestId('room-canvas').locator('canvas').boundingBox();
  expect(bounds).not.toBeNull();
  const values = await page.evaluate((id) => window.__furnitureos?.instances[id]?.screenPoints ?? [], instanceId);
  return values.map(([x, y]) => ({ x: bounds!.x + (x + 1) * bounds!.width / 2, y: bounds!.y + (1 - y) * bounds!.height / 2 }));
}

async function grabMouse(page: Page, instanceId = 'bed-against-north') {
  for (const point of await points(page, instanceId)) {
    await page.mouse.move(point.x, point.y);
    await page.mouse.down();
    await page.waitForTimeout(100);
    const state = await page.getByTestId('nudge-controls').getAttribute('data-state');
    if (state === 'dragging' || state === 'clamped') return point;
    await page.mouse.up();
  }
  throw new Error('No sampled point on the actual Product Mesh started the drag.');
}

async function grabTouch(page: Page, cdp: CDPSession, instanceId = 'bed-against-north') {
  for (const point of await points(page, instanceId)) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, id: 1 }] });
    await page.waitForTimeout(100);
    const state = await page.getByTestId('nudge-controls').getAttribute('data-state');
    if (state === 'dragging' || state === 'clamped') return point;
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  }
  throw new Error('Real touch input did not hit the Product Mesh.');
}

interface NativeCaptureEvent {
  type: string;
  pointerId: number;
  pointerType: string;
  trusted: boolean;
  captured: boolean;
}

async function recordNativeTouchCapture(page: Page) {
  await page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('[data-testid="room-canvas"] canvas')!;
    const proofWindow = window as Window & { __ticket8CaptureEvents?: NativeCaptureEvent[] };
    const events: NativeCaptureEvent[] = [];
    proofWindow.__ticket8CaptureEvents = events;
    for (const type of ['pointerdown', 'gotpointercapture', 'pointercancel', 'lostpointercapture', 'pointerup']) {
      canvas.addEventListener(type, (event) => {
        if (!(event instanceof PointerEvent) || events.length >= 64) return;
        events.push({ type: event.type, pointerId: event.pointerId,
          pointerType: event.pointerType, trusted: event.isTrusted, captured: canvas.hasPointerCapture(event.pointerId) });
      }, true);
    }
  });
}

async function nativeCaptureEvents(page: Page) {
  return page.evaluate(() => (window as Window & { __ticket8CaptureEvents?: NativeCaptureEvent[] }).__ticket8CaptureEvents ?? []);
}

async function proveRestoredTouchOrbit(page: Page, cdp: CDPSession) {
  const before = await page.evaluate(() => window.__furnitureos?.camera);
  expect(before).toHaveLength(3);
  const bounds = (await page.getByTestId('room-canvas').locator('canvas').boundingBox())!;
  const start = { x: bounds.x + 30, y: bounds.y + 80, id: 2 };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [start] });
  for (let step = 1; step <= 6; step += 1) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ ...start, x: start.x + step * 20 }] });
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForFunction((previous) => {
    const current = window.__furnitureos?.camera;
    return current && previous && Math.hypot(...current.map((value, index) => value - previous[index]!)) > 0.2;
  }, before);
  return { before, after: await page.evaluate(() => window.__furnitureos?.camera) };
}

async function expectSafePreview(page: Page) {
  await page.waitForFunction(() => {
    const debug = window.__furnitureos;
    const nudge = debug?.nudge;
    const rendered = nudge ? debug?.instances[nudge.instanceId]?.renderedTransform?.position : null;
    return nudge?.preview && rendered && Math.abs(nudge.preview[0] - rendered[0]) < 1e-12
      && Math.abs(nudge.preview[1] - rendered[2]) < 1e-12;
  });
  const proof = await page.evaluate(() => {
    const nudge = window.__furnitureos?.nudge;
    if (!nudge?.preview || !nudge.origin) return null;
    const dx = nudge.preview[0] - nudge.origin[0];
    const dz = nudge.preview[1] - nudge.origin[1];
    return { safe: nudge.constraints.every((plane) => plane.normal[0] * dx + plane.normal[1] * dz <= plane.maxDisplacementM - 1e-8),
      distance: Math.hypot(dx, dz), orbitEnabled: nudge.orbitEnabled,
      published: window.__furnitureos?.instances[nudge.instanceId]?.publishedPlacement.position,
      rendered: window.__furnitureos?.instances[nudge.instanceId]?.renderedTransform?.position };
  });
  expect(proof).not.toBeNull();
  expect(proof!.safe).toBe(true);
  expect(proof!.distance).toBeGreaterThan(0.02);
  expect(proof!.orbitEnabled).toBe(false);
  expect(proof!.rendered).not.toEqual(proof!.published);
}

test('desktop real Mesh clamps a sparse drag and commits through the real authority', async ({ page }) => {
  let regionReads = 0;
  page.on('request', (request) => { if (request.url().includes('/api/nudges/') && request.method() === 'GET') regionReads += 1; });
  await page.goto('/design');
  await ready(page);
  expect(regionReads).toBe(1);
  await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeDisabled();
  const point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 220, { steps: 1 });
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'clamped');
  await expectSafePreview(page);
  expect(regionReads).toBe(1);
  await page.screenshot({ path: join(shots, 'ticket-8-desktop-clamped-preview.png') });
  const response = page.waitForResponse((value) => value.request().method() === 'POST' && new URL(value.url()).pathname === '/api/nudges');
  await page.mouse.up();
  expect((await (await response).json()).status).toBe('accepted');
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '2');
  await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => window.__furnitureos?.nudge?.orbitEnabled)).toBe(true);
  await page.screenshot({ path: join(shots, 'ticket-8-desktop-accepted.png') });
});

test('cancel, pointercancel and lost capture restore confirmed state without a commit', async ({ page }) => {
  let commits = 0;
  page.on('request', (request) => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/nudges') commits += 1; });
  await page.goto('/design');
  await ready(page);
  let point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  await page.keyboard.press('Escape');
  await page.mouse.up();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'idle');
  for (const event of ['pointercancel', 'lostpointercapture']) {
    await ready(page);
    point = await grabMouse(page);
    await page.mouse.move(point.x, point.y + 150);
    await page.getByTestId('room-canvas').locator('canvas').dispatchEvent(event, { pointerId: 1 });
    await page.mouse.up();
    await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'idle');
    await expect.poll(() => page.evaluate(() => window.__furnitureos?.nudge?.orbitEnabled)).toBe(true);
  }
  expect(commits).toBe(0);
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '1');
});

test('intercepted rejection rolls back and uncertain transport reconciles before unlocking', async ({ page }) => {
  await page.goto('/design');
  await ready(page);
  await page.route('**/api/nudges', (route) => route.fulfill({ json: {
    status: 'rejected', code: 'controlled-rejection', currentVersion: 1, detail: 'Controlled rejection; confirmed Design retained.',
  } }));
  let point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  await page.mouse.up();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'error');
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '1');
  await page.unroute('**/api/nudges');
  await ready(page);
  await page.route('**/api/nudges', async (route) => { await route.fetch(); await route.abort('failed'); });
  const currentRead = page.waitForResponse((response) => response.request().method() === 'GET' && /\/api\/swaps\/[^/]+$/.test(new URL(response.url()).pathname));
  point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  await page.mouse.up();
  expect((await (await currentRead).json()).status).toBe('current');
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '2');
  await expect(page.getByRole('button', { name: 'Prepare Nudge' })).toBeEnabled();
});

test('a rug glides over standing furniture with the real API', async ({ page }) => {
  await page.goto('/design');
  await page.getByTestId('fixture-rug-under-bed').click();
  await ready(page, 'under-bed-rug');
  const point = await grabMouse(page, 'under-bed-rug');
  await page.mouse.move(point.x + 60, point.y + 30, { steps: 2 });
  await expectSafePreview(page);
  const response = page.waitForResponse((value) => value.request().method() === 'POST' && new URL(value.url()).pathname === '/api/nudges');
  await page.mouse.up();
  expect((await (await response).json()).status).toBe('accepted');
  await page.screenshot({ path: join(shots, 'ticket-8-rug-accepted.png') });
});

test('touch-enabled 390x844 context drives real Product touch, clamps and accepts', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  try {
    await page.goto('/design');
    await ready(page);
    expect(await page.evaluate(() => navigator.maxTouchPoints)).toBeGreaterThan(0);
    const point = await grabTouch(page, cdp);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x, y: point.y + 100, id: 1 }] });
    await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'clamped');
    await expectSafePreview(page);
    await page.screenshot({ path: join(shots, 'ticket-8-touch-clamped-preview.png') });
    const response = page.waitForResponse((value) => value.request().method() === 'POST' && new URL(value.url()).pathname === '/api/nudges');
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    expect((await (await response).json()).status).toBe('accepted');
    await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '2');
    await page.screenshot({ path: join(shots, 'ticket-8-touch-accepted.png'), fullPage: true });
    await page.evaluate(() => window.scrollTo(0, 0));
    const before = await page.evaluate(() => window.scrollY);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 300, y: 760, id: 2 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 300, y: 540, id: 2 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before);
  } finally { await context.close(); }
});

test('a second real touch cancels the captured drag and restores camera controls', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  let commits = 0;
  page.on('request', (request) => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/nudges') commits += 1; });
  try {
    await page.goto('/design');
    await ready(page);
    const point = await grabTouch(page, cdp);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x, y: point.y + 60, id: 1 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [
      { x: point.x, y: point.y + 60, id: 1 }, { x: point.x + 25, y: point.y + 60, id: 2 },
    ] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'idle');
    await expect.poll(() => page.evaluate(() => window.__furnitureos?.nudge?.orbitEnabled)).toBe(true);
    expect(commits).toBe(0);
  } finally { await context.close(); }
});

for (const termination of ['touchCancel', 'capture-release'] as const) {
  test(`native touch ${termination} rolls back a real captured Product drag without committing`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    let commits = 0;
    page.on('request', (request) => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/nudges') commits += 1; });
    try {
      await page.goto('/design');
      await ready(page);
      expect(await page.evaluate(() => navigator.maxTouchPoints)).toBeGreaterThan(0);
      const controls = page.getByTestId('nudge-controls');
      const sessionId = (await controls.getAttribute('data-session-id'))!;
      const baseline = await (await page.request.get(`/api/swaps/${sessionId}`)).json();
      expect(baseline.status).toBe('current');
      expect(baseline.version).toBe(1);
      const confirmed = baseline.design.placements[0];
      await recordNativeTouchCapture(page);
      const point = await grabTouch(page, cdp);
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x, y: point.y + 60, id: 1 }] });
      await expectSafePreview(page);
      const capture = (await nativeCaptureEvents(page)).find((event) => event.type === 'gotpointercapture');
      expect(capture).toMatchObject({ pointerType: 'touch', trusted: true, captured: true });
      expect((await nativeCaptureEvents(page)).some((event) => event.type === 'pointerdown'
        && event.pointerId === capture!.pointerId && event.pointerType === 'touch' && event.trusted)).toBe(true);
      expect(await page.getByTestId('room-canvas').locator('canvas').evaluate((canvas, id) => canvas.hasPointerCapture(id), capture!.pointerId)).toBe(true);

      if (termination === 'touchCancel') {
        // CDP browser input produces trusted touch-originated pointercancel,
        // unlike dispatchEvent, and ends the actual native touch sequence.
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
      } else {
        // Release the capture that the real Mesh drag actually established.
        await page.getByTestId('room-canvas').locator('canvas').evaluate((canvas, id) => {
          if (!canvas.hasPointerCapture(id)) throw new Error('No established native capture to release.');
          canvas.releasePointerCapture(id);
        }, capture!.pointerId);
        expect(await page.getByTestId('room-canvas').locator('canvas').evaluate((canvas, id) => canvas.hasPointerCapture(id), capture!.pointerId)).toBe(false);
        // The next real input dispatches the pending native lost-capture event;
        // ending this touch must not turn cancellation into an implicit commit.
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x + 1, y: point.y + 60, id: 1 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      }

      const expectedEvent = termination === 'touchCancel' ? 'pointercancel' : 'lostpointercapture';
      await expect.poll(async () => (await nativeCaptureEvents(page)).some((event) => event.type === expectedEvent
        && event.pointerId === capture!.pointerId && event.pointerType === 'touch' && event.trusted)).toBe(true);
      const dragEvents = (await nativeCaptureEvents(page)).filter((event) => event.pointerId === capture!.pointerId);
      expect(dragEvents.find((event) => event.type === 'lostpointercapture')).toMatchObject({ trusted: true, pointerType: 'touch', captured: false });
      if (termination === 'capture-release') expect(dragEvents.some((event) => event.type === 'pointercancel')).toBe(false);
      await expect(controls).toHaveAttribute('data-state', 'idle');
      await expect(controls).toHaveAttribute('data-version', '1');
      await expect.poll(() => page.evaluate(() => window.__furnitureos?.nudge?.preview ?? null)).toBeNull();
      await expect.poll(() => page.evaluate(() => window.__furnitureos?.instances['bed-against-north']?.renderedTransform?.position)).toEqual(confirmed.position);
      expect(await page.evaluate(() => window.__furnitureos?.instances['bed-against-north']?.renderedTransform?.yaw)).toBe(confirmed.yaw);
      expect(await page.evaluate(() => window.__furnitureos?.instances['bed-against-north']?.publishedPlacement.position)).toEqual(confirmed.position);
      expect(await page.evaluate(() => window.__furnitureos?.instances['bed-against-north']?.publishedPlacement.yaw)).toBe(confirmed.yaw);
      await expect.poll(() => page.evaluate(() => window.__furnitureos?.nudge?.orbitEnabled)).toBe(true);
      expect(commits).toBe(0);
      await page.screenshot({ path: join(shots, `ticket-8-fix-1-${termination}-rollback.png`) });
      const orbit = await proveRestoredTouchOrbit(page, cdp);
      const current = await (await page.request.get(`/api/swaps/${sessionId}`)).json();
      expect(current.status).toBe('current');
      expect(current.version).toBe(1);
      expect(current.design.placements).toEqual(baseline.design.placements);
      expect(commits).toBe(0);
      expect(await page.evaluate(() => window.__furnitureos?.nudge?.preview ?? null)).toBeNull();
      writeFileSync(join(shots, `ticket-8-fix-1-${termination}-native-events.json`), JSON.stringify({
        viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, termination,
        events: await nativeCaptureEvents(page), orbit, commits, version: current.version,
        confirmedPosition: confirmed.position,
        restoredPosition: await page.evaluate(() => window.__furnitureos?.instances['bed-against-north']?.renderedTransform?.position),
      }, null, 2));
    } finally { await context.close(); }
  });
}

test('an external real Swap wins the version race and stale Nudge reconciles', async ({ page, request }) => {
  await page.goto('/design');
  await ready(page);
  const controls = page.getByTestId('nudge-controls');
  const sessionId = await controls.getAttribute('data-session-id');
  const point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  const winner = await request.post('/api/swaps', { data: {
    sessionId, expectedVersion: 1, instanceId: 'bed-against-north',
    replacementProductId: 'bed-rivet-jonathan-queen-walnut',
  } });
  expect((await winner.json()).status).toBe('accepted');
  const response = page.waitForResponse((value) => value.request().method() === 'POST' && new URL(value.url()).pathname === '/api/nudges');
  await page.mouse.up();
  expect((await (await response).json()).status).toBe('stale-version');
  await expect(controls).toHaveAttribute('data-version', '2');
  await page.waitForFunction(() => window.__furnitureos?.instances['bed-against-north']?.productId === 'bed-rivet-jonathan-queen-walnut');
});

test('failed recovery retains the confirmed Design and shared lock until Retry', async ({ page }) => {
  await page.goto('/design');
  await ready(page);
  await page.route('**/api/nudges', (route) => route.abort('failed'));
  await page.route(/\/api\/swaps\/[^/?]+$/, (route) => route.abort('failed'));
  const point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  await page.mouse.up();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'blocked');
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '1');
  await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeDisabled();
  await page.unroute(/\/api\/swaps\/[^/?]+$/);
  await page.getByRole('button', { name: 'Retry current Design' }).click();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'idle');
  await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeEnabled();
});

test('a late region response cannot attach to a newly selected fixture session', async ({ page }) => {
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const entered = new Promise<void>((resolve) => { started = resolve; });
  await page.route('**/api/nudges/*/region?*', async (route) => {
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response });
  });
  await page.goto('/design');
  const controls = page.getByTestId('nudge-controls');
  const oldSession = await controls.getAttribute('data-session-id');
  await page.getByRole('button', { name: 'Prepare Nudge' }).click();
  await entered;
  await page.waitForFunction(() => window.__furnitureos?.instances['bed-against-north']?.actualFrameRendered);
  const pendingPoint = (await points(page, 'bed-against-north'))[4]!;
  await page.mouse.move(pendingPoint.x, pendingPoint.y);
  await page.mouse.down();
  await page.mouse.up();
  await expect(controls).toHaveAttribute('data-state', 'pending');
  expect(await page.evaluate(() => window.__furnitureos?.nudge?.preview)).toBeNull();
  await page.getByTestId('fixture-rug-under-bed').click();
  await expect(controls).not.toHaveAttribute('data-session-id', oldSession!);
  const ownedSession = await controls.getAttribute('data-session-id');
  release();
  await expect(controls).toHaveAttribute('data-state', 'idle');
  await expect(controls).toHaveAttribute('data-session-id', ownedSession!);
  await expect(page.getByRole('button', { name: 'Prepare Nudge' })).toBeEnabled();
});

test('a late accepted Nudge cannot resurrect a fixture that lost ownership', async ({ page }) => {
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const entered = new Promise<void>((resolve) => { started = resolve; });
  await page.route('**/api/nudges', async (route) => {
    const response = await route.fetch();
    expect((await response.json()).status).toBe('accepted');
    started();
    await held;
    await route.fulfill({ response });
  });
  await page.goto('/design');
  await ready(page);
  const oldSession = await page.getByTestId('nudge-controls').getAttribute('data-session-id');
  const point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  await page.mouse.up();
  await entered;
  await page.getByTestId('fixture-rug-under-bed').click();
  await expect(page.getByTestId('nudge-controls')).not.toHaveAttribute('data-session-id', oldSession!);
  const ownedSession = await page.getByTestId('nudge-controls').getAttribute('data-session-id');
  release();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-session-id', ownedSession!);
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '1');
});

test('intercepted thin-bound certificate consumer clamps a sparse jump without endpoint projection', async ({ page }) => {
  await page.route('**/api/nudges/*/region?*', async (route) => {
    const response = await route.fetch();
    const region = await response.json();
    expect(region.status).toBe('available');
    // Controlled narrower subset of a real certificate tests the browser
    // consumer; physical thin-obstacle authority is covered by backend tests.
    region.constraints.push({ normal: [1, 0], maxDisplacementM: 0.015 });
    region.constraintCount += 1;
    await route.fulfill({ json: region });
  });
  await page.goto('/design');
  await ready(page);
  const point = await grabMouse(page);
  await page.mouse.move(point.x + 250, point.y + 220, { steps: 1 });
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'clamped');
  const dx = await page.evaluate(() => {
    const nudge = window.__furnitureos?.nudge;
    return nudge!.preview![0] - nudge!.origin![0];
  });
  expect(dx).toBeGreaterThan(0);
  expect(dx).toBeLessThan(0.015);
  await page.keyboard.press('Escape');
  await page.mouse.up();
});

test('controlled live generation uses the same real Nudge authority and clears ownership on style change', async ({ page, request }) => {
  const config = { ...(await (await request.get('/api/live-bedroom/config')).json()), realCallsEnabled: true };
  const design = await (await request.post('/api/design-resolution', { data: { fixtureId: 'against-wall', maxCandidates: 128 } })).json();
  await page.route('**/api/live-bedroom/config', (route) => route.fulfill({ json: config }));
  await page.route('**/api/live-bedroom/variants', (route) => route.fulfill({ contentType: 'application/x-ndjson', body: resultStream({
    status: 'solved', generationId: 'controlled-nudge-live', referenceId: 'ref-01',
    providerModel: 'controlled-no-provider-call', providerCalls: 0, modelLatencyMs: 0,
    usage: { known: true, inputTokens: 0, outputTokens: 0, costUsd: 0 }, design,
  }) }));
  await page.goto('/design/live-bedroom');
  await page.getByRole('radio', { name: 'Bedroom' }).check();
  await page.getByRole('radio', { name: /Soft neutrals and warm wood/ }).check();
  await page.getByRole('button', { name: 'Generate bedroom' }).click();
  await ready(page);
  const point = await grabMouse(page);
  await page.mouse.move(point.x, point.y + 150);
  const response = page.waitForResponse((value) => value.request().method() === 'POST' && new URL(value.url()).pathname === '/api/nudges');
  await page.mouse.up();
  expect((await (await response).json()).status).toBe('accepted');
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '2');
  await page.screenshot({ path: join(shots, 'ticket-8-live-controlled-accepted.png') });
  const other = page.locator('input[name="reference-image"]').nth(1);
  await other.check();
  await expect(page.getByTestId('nudge-controls')).toHaveCount(0);
  await expect(page.getByTestId('live-idle')).toBeVisible();
});

test('transport, unavailable and malformed region responses never enable a preview and can be retried', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/nudges/*/region?*', async (route) => {
    attempts += 1;
    if (attempts === 1) { await route.abort('failed'); return; }
    if (attempts === 2) { await route.fulfill({ json: {
      status: 'unavailable', currentVersion: 1, instanceId: 'bed-against-north', detail: 'Controlled unavailable geometry.',
    } }); return; }
    if (attempts === 3) {
      const response = await route.fetch();
      const region = await response.json();
      region.constraints[0].normal = [2, 0];
      await route.fulfill({ json: region });
      return;
    }
    await route.continue();
  });
  await page.goto('/design');
  for (const state of ['error', 'unavailable', 'unavailable']) {
    await page.getByRole('button', { name: /Prepare Nudge|Retry Nudge/ }).click();
    await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', state);
    await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-version', '1');
    expect(await page.evaluate(() => window.__furnitureos?.nudge?.preview ?? null)).toBeNull();
    await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeEnabled();
  }
  await ready(page);
  expect(attempts).toBe(4);
  await page.getByRole('button', { name: 'Cancel preview' }).click();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'idle');
});
