import { expect, test, type Page } from '@playwright/test';

const loadedRoom = async (page: Page) => {
  await expect(page.getByTestId('api-preview')).toBeVisible();
  await page.waitForFunction(() => window.__furnitureos?.ready && (window.__furnitureos.framesRendered ?? 0) > 3);
};
const bodyStyle = (page: Page) => page.locator('body').evaluate((body) => {
  const style = getComputedStyle(body);
  return { background: style.backgroundColor, color: style.color, font: style.fontFamily, lineHeight: style.lineHeight,
    scroll: getComputedStyle(document.documentElement).scrollbarWidth, overflowX: style.overflowX };
});

test('landing uses local fonts and metadata without fetching Room code, API or assets', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));
  await page.goto('/');
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveTitle('FurnitureOS — AI powered room design');
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', 'Turn a real Room Capture into a furnished Design assembled from real Products.');
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/icon.svg');
  const fonts = await page.evaluate(() => ({
    manrope: document.fonts.check('500 88px "Manrope Variable"'),
    mono: document.fonts.check('400 12px "Roboto Mono"'),
    hero: getComputedStyle(document.querySelector('h1')!).fontFamily,
  }));
  expect(fonts.manrope && fonts.mono).toBe(true);
  expect(fonts.hero).toContain('Manrope Variable');
  expect(requests.filter((url) => url.endsWith('.woff2'))).toHaveLength(2);
  expect(requests.filter((url) => url.endsWith('.woff2')).every((url) => new URL(url).origin === new URL(page.url()).origin)).toBe(true);
  await page.getByRole('button', { name: 'Explore a sample Design' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Swap to Cove chair' }).click();
  await page.keyboard.press('Escape');
  expect(requests.filter((url) => /\/api\/|\/products\/|\/decoders\/|RoomCanvas|DesignPage|basis_transcoder|\.gltf|\.ktx2/.test(url))).toEqual([]);
  expect(await page.evaluate(() => window.__furnitureos)).toBeUndefined();
});

test('client links, back and forward preserve route styles, metadata and canvas bounds', async ({ page }) => {
  await page.goto('/design');
  await loadedRoom(page);
  const designStyle = await bodyStyle(page);
  const canvas = await page.getByTestId('room-canvas').boundingBox();
  await page.getByRole('link', { name: 'FurnitureOS home' }).click();
  await expect(page).toHaveURL(/\/$/);
  const landingStyle = await bodyStyle(page);
  expect(landingStyle.background).toBe('rgb(253, 254, 246)');
  expect(landingStyle.scroll).toBe('none');
  expect(landingStyle.font).toContain('Manrope Variable');
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Room preview' }).click();
  await loadedRoom(page);
  expect(await bodyStyle(page)).toEqual(designStyle);
  expect(await page.getByTestId('room-canvas').boundingBox()).toEqual(canvas);
  await expect(page).toHaveTitle('FurnitureOS — Room preview');
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', 'A real, real-scale Product placed in a Room Shell.');
  await page.goBack();
  await expect(page).toHaveTitle('FurnitureOS — AI powered room design');
  expect(await bodyStyle(page)).toEqual(landingStyle);
  await page.goForward();
  await loadedRoom(page);
  expect(await bodyStyle(page)).toEqual(designStyle);
  await page.getByRole('link', { name: 'FurnitureOS home' }).click();
  await page.getByRole('button', { name: 'Explore a sample Design' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
});

for (const route of ['/design', '/design/']) {
  test(`direct visit and refresh of ${route} renders the authoritative Room`, async ({ page }) => {
    await page.goto(route);
    await loadedRoom(page);
    await page.reload();
    await loadedRoom(page);
    await expect(page.getByTestId('fit-status')).toHaveAttribute('data-fit', 'fits');
  });
}

test('unknown routes have an accessible recovery and missing assets/API stay 404', async ({ page, request }) => {
  await page.goto('/unknown/room');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found');
  await expect(page).toHaveTitle('Page not found — FurnitureOS');
  await page.getByRole('link', { name: 'FurnitureOS home' }).click();
  await expect(page.locator('.hero')).toBeVisible();
  for (const path of ['/assets/missing.js', '/images/missing.jpg', '/products/missing.gltf', '/decoders/missing.wasm', '/api/missing', '/missing.css']) {
    expect((await request.get(path)).status(), path).toBe(404);
  }
  await page.goto('/catalogue-gallery');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found');
  expect((await request.get('/api/catalogue-gallery')).status()).toBe(404);
  expect((await request.get('/icon.svg')).headers()['content-type']).toContain('image/svg+xml');
});

test('loading status is announced before the preview API returns', async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/api/preview-design', async (route) => { await pending; await route.continue(); });
  await page.goto('/design');
  await expect(page.getByTestId('api-loading')).toHaveAttribute('role', 'status');
  release();
  await loadedRoom(page);
});

test('a failed lazy Room module leaves an accessible reload and home path', async ({ page }) => {
  await page.route('**/assets/DesignPage-*.js', (route) => route.abort());
  await page.goto('/design');
  await expect(page.getByRole('heading', { name: 'Preview could not open' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reload preview' })).toBeVisible();
  await page.getByRole('link', { name: 'FurnitureOS home' }).click();
  await expect(page.locator('.hero')).toBeVisible();
});

test('mobile sample offers the real preview and leaving it resets focus and styles', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Explore sample', exact: true }).first().click();
  await page.getByRole('dialog').getByRole('link', { name: 'Open the real Room preview' }).click();
  await loadedRoom(page);
  await page.getByRole('link', { name: 'FurnitureOS home' }).click();
  await expect(page.locator('.hero')).toBeVisible();
  await expect(page.getByRole('dialog')).toBeHidden();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.locator('#root')).toBeFocused();
});
