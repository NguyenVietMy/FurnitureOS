import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const root = fileURLToPath(new URL('..', import.meta.url));
const productId = 'bed-prudence-tufted-queen-natural';
const manifest = JSON.parse(readFileSync(join(root, 'public', 'products', productId, 'asset-manifest.json'), 'utf8')) as { source: { url: string; bounds: { size: number[] } }; normalization: { frontAxis: string } };
const shots = join(root, 'test-results', 'screenshots'); mkdirSync(shots, { recursive: true });
interface Scene { ready: boolean; productId: string; activeLod: number; framesRendered: number; worldBounds: { min: number[]; max: number[]; size: number[] } | null; placement: { wallId: string | null } | null; textures: { requested: number; decoded: number; fallback: number }; camera: number[] | null; }
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

test('renders FastAPI data with the real Product, attribution, orbit, LODs and same-origin assets', async ({ page }) => {
  const apiResponses: string[] = []; const responses: { url: string; status: number }[] = [];
  page.on('response', (response) => { responses.push({ url: response.url(), status: response.status() }); if (response.url().includes('/api/preview-design')) apiResponses.push(response.url()); });
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
  await page.unroute('**/*.ktx2'); await page.route('**/api/preview-design', (route) => route.abort()); await page.reload(); await expect(page.getByTestId('api-error')).toContainText('Preview data is unavailable'); const retry = page.getByRole('button', { name: 'Retry' }); await expect(retry).toBeVisible(); await page.unroute('**/api/preview-design'); await retry.click(); await expect(page.getByTestId('api-preview')).toBeVisible(); await waitForProduct(page); await expect(page.getByTestId('design-panel')).toContainText('Prudence Tufted Queen Bed');
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
