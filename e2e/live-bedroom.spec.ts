import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

const root = fileURLToPath(new URL('..', import.meta.url));
const shots = process.env.FURNITUREOS_EVIDENCE_DIR ?? join(root, 'test-results', 'screenshots');
mkdirSync(shots, { recursive: true });

test('controlled live choice renders every real Mesh and clears stale success on failure', async ({ page, request }) => {
  const configResponse = await request.get('/api/live-bedroom/config');
  const config = { ...(await configResponse.json()), realCallsEnabled: true };
  const designResponse = await request.post('/api/design-resolution', {
    data: { fixtureId: 'zoned-repairable', maxCandidates: 256 },
  });
  const design = await designResponse.json();
  expect(design.status).toBe('solved');
  let generationRequests = 0;
  let releaseFirst!: () => void;
  let releaseFailure!: () => void;
  let markFirstStarted!: () => void;
  let markFailureStarted!: () => void;
  const firstStarted = new Promise<void>((resolve) => { markFirstStarted = resolve; });
  const failureStarted = new Promise<void>((resolve) => { markFailureStarted = resolve; });
  const holdFirst = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const holdFailure = new Promise<void>((resolve) => { releaseFailure = resolve; });

  await page.route('**/api/live-bedroom/config', (route) => route.fulfill({ json: config }));
  await page.route('**/api/live-bedroom/generate', async (route) => {
    generationRequests += 1;
    if (generationRequests === 1) {
      markFirstStarted();
      await holdFirst;
      await route.fulfill({ json: {
        status: 'solved', generationId: 'controlled-generation-1', referenceId: 'ref-01',
        providerModel: 'claude-opus-5', providerCalls: 2, modelLatencyMs: 1234,
        usage: { known: true, inputTokens: 100, outputTokens: 20, costUsd: 0.001 }, design,
      } });
      return;
    }
    markFailureStarted();
    await holdFailure;
    await route.fulfill({ json: {
      status: 'failed', generationId: 'controlled-generation-2', referenceId: 'ref-01',
      code: 'no-valid-design', detail: 'No valid Design after the bounded repairs.',
      providerModel: 'claude-opus-5', providerCalls: 3, modelLatencyMs: 1500,
      usage: { known: false }, designFailure: null,
    } });
  });

  await page.goto('/design');
  await expect(page.getByTestId('api-preview')).toBeVisible();
  await page.getByRole('link', { name: 'Generate a live bedroom' }).click();
  await expect(page.getByTestId('live-bedroom')).toBeVisible();
  expect(generationRequests).toBe(0);
  await page.getByRole('radio', { name: 'Bedroom' }).check();
  await page.getByRole('radio', { name: /Soft neutrals and warm wood/ }).check();
  await expect(page.getByRole('button', { name: 'Generate bedroom' })).toBeEnabled();
  await page.getByRole('button', { name: 'Generate bedroom' }).click();
  await firstStarted;
  await expect(page.getByTestId('live-loading')).toBeVisible();
  releaseFirst();
  await page.waitForFunction(() => window.__furnitureos?.usefulView.status === 'complete', undefined, { timeout: 60_000 });
  const proof = await page.evaluate(() => JSON.parse(JSON.stringify(window.__furnitureos)));
  expect(proof.generationId).toBe('controlled-generation-1');
  expect(proof.usefulView.expectedPlacements).toBe(design.placements.length);
  expect(proof.usefulView.renderedPlacements).toBe(design.placements.length);
  expect(proof.usefulView.materialsReady).toBe(true);
  expect(proof.usefulView.texturesReady).toBe(true);
  expect(proof.usefulView.durationMs).toBeGreaterThanOrEqual(0);
  expect(Object.values(proof.instances).every((item: any) => item.actualFrameRendered
    && item.screenVisible
    && item.activeMeshCount > 0
    && item.mainCameraMeshCount === item.activeMeshCount)).toBe(true);
  writeFileSync(join(shots, 'ticket-6-live-controlled-scene.json'), `${JSON.stringify(proof, null, 2)}\n`);
  await page.screenshot({ path: join(shots, 'ticket-6-live-controlled-solved.png') });

  await page.getByRole('button', { name: 'Generate bedroom' }).click();
  await failureStarted;
  await expect(page.getByTestId('live-loading')).toBeVisible();
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => ({
    generationId: window.__furnitureos?.generationId,
    instances: Object.keys(window.__furnitureos?.instances ?? {}).length,
    status: window.__furnitureos?.usefulView.status,
  }))).toEqual({ generationId: null, instances: 0, status: 'not-measured' });
  releaseFailure();
  await expect(page.getByTestId('live-failure')).toBeVisible();
  await expect(page.getByText('No bedroom Design fit this Room.')).toBeVisible();
  await expect(page.getByText('Generation ID').locator('..')).toContainText('controlled-generation-2');
  expect(await page.evaluate(() => ({
    generationId: window.__furnitureos?.generationId,
    instances: Object.keys(window.__furnitureos?.instances ?? {}).length,
    usefulView: window.__furnitureos?.usefulView,
    textures: window.__furnitureos?.textures,
  }))).toEqual({
    generationId: null,
    instances: 0,
    usefulView: {
      status: 'not-measured', receivedAtMs: null, completedAtMs: null, durationMs: null,
      expectedPlacements: 0, renderedPlacements: 0, materialsReady: false, texturesReady: false,
    },
    textures: { requested: 0, decoded: 0, fallback: 0 },
  });
  await page.screenshot({ path: join(shots, 'ticket-6-live-controlled-failed.png') });
});

test('replaced live request cannot publish a late Design', async ({ page, request }) => {
  const configResponse = await request.get('/api/live-bedroom/config');
  const config = { ...(await configResponse.json()), realCallsEnabled: true };
  const designResponse = await request.post('/api/design-resolution', {
    data: { fixtureId: 'zoned-repairable', maxCandidates: 256 },
  });
  const design = await designResponse.json();
  let release!: () => void;
  let requestStarted!: () => void;
  const started = new Promise<void>((resolve) => { requestStarted = resolve; });
  const pending = new Promise<void>((resolve) => { release = resolve; });

  await page.route('**/api/live-bedroom/config', (route) => route.fulfill({ json: config }));
  await page.route('**/api/live-bedroom/generate', async (route) => {
    requestStarted();
    await pending;
    try {
      await route.fulfill({ json: {
        status: 'solved', generationId: 'late-generation', referenceId: 'ref-01',
        providerModel: 'claude-opus-5', providerCalls: 1, modelLatencyMs: 50,
        usage: { known: false }, design,
      } });
    } catch {
      // The browser is allowed to cancel the superseded transport.
    }
  });

  await page.goto('/design/live-bedroom');
  await page.getByRole('radio', { name: 'Bedroom' }).check();
  await page.getByRole('radio', { name: /Soft neutrals and warm wood/ }).check();
  await page.getByRole('button', { name: 'Generate bedroom' }).click();
  await started;
  await page.getByRole('radio', { name: /Light wood and simple lines/ }).check();
  await expect(page.getByTestId('live-idle')).toBeVisible();
  expect(await page.evaluate(() => ({
    generationId: window.__furnitureos?.generationId,
    instances: Object.keys(window.__furnitureos?.instances ?? {}).length,
    status: window.__furnitureos?.usefulView.status,
  }))).toEqual({ generationId: null, instances: 0, status: 'not-measured' });
  release();
  await page.waitForTimeout(300);
  await expect(page.getByTestId('live-idle')).toBeVisible();
  await expect(page.getByTestId('room-canvas')).toHaveCount(0);
  await expect(page.getByText('late-generation')).toHaveCount(0);
  expect(await page.evaluate(() => ({
    generationId: window.__furnitureos?.generationId,
    instances: Object.keys(window.__furnitureos?.instances ?? {}).length,
    status: window.__furnitureos?.usefulView.status,
  }))).toEqual({ generationId: null, instances: 0, status: 'not-measured' });
});

test('live bedroom choices remain usable without horizontal overflow on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/design/live-bedroom');
  await expect(page.getByRole('heading', { name: 'Choose the feeling, then generate' })).toBeVisible();
  const widths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client);
  await expect(page.getByText('Generation is not available right now.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate bedroom' })).toBeDisabled();
});
