import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const evidenceDir = process.env.FURNITUREOS_EVIDENCE_DIR;
test.describe.configure({ timeout: 240_000 });

test('@measurement renders all 20 real Products progressively and exports observable evidence', async ({ page }) => {
  const responses: string[] = [];
  page.on('response', (response) => {
    if (/\/products\/.+\/(lod[012]\.gltf|textures\/.+\.ktx2)$/.test(new URL(response.url()).pathname)) {
      responses.push(new URL(response.url()).pathname);
    }
  });
  await page.goto('/catalogue-gallery');
  await expect(page.getByTestId('catalogue-gallery')).toBeVisible();
  await expect(page.getByTestId('product-count')).toHaveText('20');
  await page.waitForFunction(() => {
    const measurement = window.__catalogueMeasurement;
    return Boolean(measurement)
      && measurement!.allVisibleMs !== null
      && Object.values(measurement!.products).every((product) =>
        product.initialLod === 2
        && product.refinements.some((event) => event.lod === 1)
        && product.refinements.some((event) => event.lod === 0));
  }, undefined, { timeout: 240_000 });
  const measurement = await page.evaluate(() => window.__catalogueMeasurement!);
  expect(measurement).toBeDefined();
  expect(Object.keys(measurement.products)).toHaveLength(20);
  for (const product of Object.values(measurement.products)) {
    expect(product.error).toBeNull();
    expect(product.initialLod).toBe(2);
    expect(product.renderedFrames).toBeGreaterThanOrEqual(3);
    expect(product.firstVisibleMs).not.toBeNull();
    expect(product.refinements.map((event) => event.lod)).toEqual(expect.arrayContaining([1, 0]));
    expect(product.refinements.find((event) => event.lod === 1)!.visibleMs).toBeGreaterThanOrEqual(product.firstVisibleMs!);
    expect(product.refinements.find((event) => event.lod === 0)!.visibleMs).toBeGreaterThanOrEqual(
      product.refinements.find((event) => event.lod === 1)!.visibleMs,
    );
  }
  expect(new Set(responses.filter((url) => url.endsWith('/lod2.gltf'))).size).toBe(20);
  expect(new Set(responses.filter((url) => url.endsWith('/lod1.gltf'))).size).toBe(20);
  expect(new Set(responses.filter((url) => url.endsWith('/lod0.gltf'))).size).toBe(20);

  if (evidenceDir) {
    await mkdir(evidenceDir, { recursive: true });
    await writeFile(join(evidenceDir, 'automated-gallery-measurement.json'), `${JSON.stringify(measurement, null, 2)}\n`);
    await page.screenshot({ path: join(evidenceDir, 'automated-gallery-desktop.png'), fullPage: true });
  }
});

test('@measurement reports a real asset error and can restart after recovery', async ({ page }) => {
  let block = true;
  await page.route('**/products/bed-alkove-hayes-double-wild-oak/lod2.gltf', (route) => {
    if (block) return route.abort('failed');
    return route.continue();
  });
  await page.goto('/catalogue-gallery');
  await expect(page.getByTestId('gallery-load-error')).toBeVisible();
  expect(await page.evaluate(() => window.__catalogueMeasurement?.products['bed-alkove-hayes-double-wild-oak']?.error)).toBeTruthy();
  expect(await page.evaluate(() => window.__catalogueMeasurement?.allVisibleMs)).toBeNull();
  block = false;
  await page.getByRole('button', { name: 'Restart measurement' }).click();
  await expect(page.getByTestId('gallery-load-error')).toHaveCount(0);
  await page.waitForFunction(() => {
    const measurement = window.__catalogueMeasurement;
    return Boolean(measurement) && measurement!.allVisibleMs !== null;
  }, undefined, { timeout: 120_000 });
  const recovered = await page.evaluate(() => window.__catalogueMeasurement);
  expect(recovered).toBeDefined();
  expect(recovered?.products['bed-alkove-hayes-double-wild-oak']?.error).toBeNull();
});
