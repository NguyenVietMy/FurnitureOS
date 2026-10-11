import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const root = fileURLToPath(new URL('..', import.meta.url));
const shots = process.env.FURNITUREOS_EVIDENCE_DIR ?? join(root, 'test-results', 'screenshots');
mkdirSync(shots, { recursive: true });

interface SceneInstance {
  productId: string;
  ready: boolean;
  publishedPlacement: { position: number[]; yaw: number };
  renderedTransform: { position: number[]; yaw: number } | null;
  meshCount: number;
}

async function sceneInstance(page: Page, instanceId: string): Promise<SceneInstance> {
  return page.evaluate((id) => JSON.parse(JSON.stringify(window.__furnitureos?.instances[id])), instanceId);
}

async function expectNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client);
}

async function checkCompatibleProducts(page: Page) {
  await page.getByRole('button', { name: /Check compatible Products|Retry compatible Products/ }).click();
}

test('candidate checks require an explicit scoped action and failed reads can be retried', async ({ page }) => {
  let candidateAttempts = 0;
  await page.route('**/api/swaps/*/candidates?*', async (route) => {
    candidateAttempts += 1;
    if (candidateAttempts === 1) {
      await route.abort('failed');
      return;
    }
    await route.continue();
  });

  await page.goto('/design');
  const controls = page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version', '1');
  const firstSessionId = await controls.getAttribute('data-session-id');
  expect(candidateAttempts).toBe(0);

  await page.getByTestId('fixture-rug-under-bed').click();
  await expect(controls).not.toHaveAttribute('data-session-id', firstSessionId!);
  await expect(page.getByRole('button', { name: 'Check compatible Products' })).toBeVisible();
  expect(candidateAttempts).toBe(0);

  await checkCompatibleProducts(page);
  await expect(page.getByRole('button', { name: 'Retry compatible Products' })).toBeVisible();
  expect(candidateAttempts).toBe(1);

  const responsePromise = page.waitForResponse((response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/candidates'));
  await checkCompatibleProducts(page);
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(candidateAttempts).toBe(2);
  await expect(page.getByRole('combobox', { name: 'Compatible Product' })).toBeVisible();
});

test('fixture Swap uses the real API and Mesh while preserving the exact transform', async ({ page }) => {
  await page.goto('/design');
  const controls = page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version', '1');
  const placement = page.getByRole('combobox', { name: 'Placement to Swap' });
  const candidates = page.getByRole('combobox', { name: 'Compatible Product' });
  await checkCompatibleProducts(page);
  await expect(candidates).toBeVisible();
  await expect(candidates.locator('option[value="bed-rivet-jonathan-queen-walnut"]')).toHaveCount(1);
  const instanceId = await placement.inputValue();
  await page.waitForFunction((id) => window.__furnitureos?.instances[id]?.ready, instanceId, { timeout: 60_000 });
  const before = await sceneInstance(page, instanceId);

  const button = page.getByRole('button', { name: 'Swap Product' });
  await button.focus();
  await page.keyboard.press('Enter');
  await expect(controls).toHaveAttribute('data-version', '2');
  await page.waitForFunction(
    (id) => window.__furnitureos?.instances[id]?.ready
      && window.__furnitureos.instances[id]?.productId === 'bed-rivet-jonathan-queen-walnut',
    instanceId,
    { timeout: 60_000 },
  );
  const after = await sceneInstance(page, instanceId);
  expect(after.productId).toBe('bed-rivet-jonathan-queen-walnut');
  expect(after.productId).not.toBe(before.productId);
  expect(after.publishedPlacement).toEqual(before.publishedPlacement);
  expect(after.renderedTransform?.position).toEqual(before.renderedTransform?.position);
  expect(after.renderedTransform?.yaw).toBe(before.renderedTransform?.yaw);
  expect(after.meshCount).toBeGreaterThan(0);
  await expect(page.getByTestId('design-panel')).toContainText('Jonathan Wood Queen Bed');
  await expect(page.getByTestId('design-panel')).toContainText('Attribution');
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(controls).toBeVisible();
  await expect(placement).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: join(shots, 'ticket-7-fixture-swap-mobile.png'), fullPage: true });
});

test('same-role rejection details and an explained empty candidate list are accessible', async ({ page }) => {
  await page.goto('/design');
  await expect(page.getByTestId('swap-controls')).toBeVisible();
  await checkCompatibleProducts(page);
  const reasons = page.getByText('Why other same-role Products do not fit');
  await expect(reasons).toBeVisible();
  await reasons.click();
  await expect(page.getByTestId('swap-controls')).toContainText('is not touching wall-north');

  await page.getByTestId('fixture-matching-nightstands').click();
  await checkCompatibleProducts(page);
  await expect(page.getByTestId('swap-empty')).toContainText('No other Catalogue Product preserves this complete Design');
  await expect(page.locator('.swap-button')).toBeDisabled();
  await expect(page.getByText('Why other same-role Products do not fit')).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test('stale browser proposal never installs and explicit refresh renders the winner', async ({ page, request }) => {
  await page.goto('/design');
  const controls = page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version', '1');
  await checkCompatibleProducts(page);
  const sessionId = await controls.getAttribute('data-session-id');
  const instanceId = await page.getByRole('combobox', { name: 'Placement to Swap' }).inputValue();
  const replacementProductId = await page.getByRole('combobox', { name: 'Compatible Product' }).inputValue();
  expect(sessionId).toBeTruthy();

  const winner = await request.post('/api/swaps', { data: {
    sessionId, expectedVersion: 1, instanceId, replacementProductId,
  } });
  expect((await winner.json()).status).toBe('accepted');

  await page.getByRole('button', { name: 'Swap Product' }).click();
  await expect(page.getByRole('button', { name: 'Refresh current Design' })).toBeVisible();
  expect((await sceneInstance(page, instanceId)).productId).not.toBe(replacementProductId);
  await page.getByRole('button', { name: 'Refresh current Design' }).click();
  await expect(controls).toHaveAttribute('data-version', '2');
  await page.waitForFunction(
    ({ id, productId }) => window.__furnitureos?.instances[id]?.ready
      && window.__furnitureos.instances[id]?.productId === productId,
    { id: instanceId, productId: replacementProductId },
    { timeout: 60_000 },
  );
});

test('a dropped post-commit response reconciles before controls unlock', async ({ page }) => {
  await page.goto('/design');
  const controls = page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version', '1');
  await checkCompatibleProducts(page);
  const placement = page.getByRole('combobox', { name: 'Placement to Swap' });
  const candidates = page.getByRole('combobox', { name: 'Compatible Product' });
  const instanceId = await placement.inputValue();
  const replacementProductId = await candidates.inputValue();
  let markCommitted!: () => void;
  let releaseResponse!: () => void;
  const committed = new Promise<void>((resolve) => { markCommitted = resolve; });
  const holdResponse = new Promise<void>((resolve) => { releaseResponse = resolve; });

  await page.route('**/api/swaps', async (route) => {
    const response = await route.fetch();
    expect((await response.json()).status).toBe('accepted');
    markCommitted();
    await holdResponse;
    await route.abort('failed');
  });
  try {
    await page.getByRole('button', { name: 'Swap Product' }).click();
    await committed;
    await expect(placement).toBeDisabled();
    await expect(candidates).toBeDisabled();
    await expect(page.locator('.swap-button')).toBeDisabled();
  } finally {
    releaseResponse();
  }
  await expect(controls).toHaveAttribute('data-version', '2');
  await page.waitForFunction(
    ({ id, productId }) => window.__furnitureos?.instances[id]?.ready
      && window.__furnitureos.instances[id]?.productId === productId,
    { id: instanceId, productId: replacementProductId },
    { timeout: 60_000 },
  );
  await expect(placement).toBeEnabled();
  await expect(page.getByText('Current Design version 2 restored.')).toBeVisible();
});

test('a delayed accepted response cannot resurrect a fixture that lost view ownership', async ({ page }) => {
  await page.goto('/design');
  await expect(page.getByTestId('swap-controls')).toHaveAttribute('data-version', '1');
  await checkCompatibleProducts(page);
  let markCommitted!: () => void;
  let releaseResponse!: () => void;
  const committed = new Promise<void>((resolve) => { markCommitted = resolve; });
  const holdResponse = new Promise<void>((resolve) => { releaseResponse = resolve; });

  await page.route('**/api/swaps', async (route) => {
    const response = await route.fetch();
    expect((await response.json()).status).toBe('accepted');
    markCommitted();
    await holdResponse;
    await route.fulfill({ response });
  });
  let newSessionId: string | null = null;
  try {
    await page.getByRole('button', { name: 'Swap Product' }).click();
    await committed;
    await page.getByTestId('fixture-rug-under-bed').click();
    await expect(page.getByTestId('design-panel')).toContainText('Arrow Wool Rug');
    newSessionId = await page.getByTestId('swap-controls').getAttribute('data-session-id');
  } finally {
    releaseResponse();
  }
  await page.waitForTimeout(300);
  await expect(page.getByTestId('fixture-rug-under-bed')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('design-panel')).toContainText('Arrow Wool Rug');
  expect(newSessionId).toBeTruthy();
  await expect(page.getByTestId('swap-controls')).toHaveAttribute('data-session-id', newSessionId!);
});

test('stale candidate reads lock controls and expose current-Design refresh', async ({ page, request }) => {
  await page.goto('/design');
  await page.getByTestId('fixture-rug-under-bed').click();
  const controls = page.getByTestId('swap-controls');
  await expect(controls).toHaveAttribute('data-version', '1');
  const sessionId = await controls.getAttribute('data-session-id');
  const placement = page.getByRole('combobox', { name: 'Placement to Swap' });
  await placement.selectOption('rug-bed');
  await checkCompatibleProducts(page);
  const candidates = page.getByRole('combobox', { name: 'Compatible Product' });
  await expect(candidates.locator('option[value="bed-rivet-jonathan-queen-walnut"]')).toHaveCount(1);
  const winner = await request.post('/api/swaps', { data: {
    sessionId,
    expectedVersion: 1,
    instanceId: 'rug-bed',
    replacementProductId: 'bed-rivet-jonathan-queen-walnut',
  } });
  expect((await winner.json()).status).toBe('accepted');

  await placement.selectOption('under-bed-rug');
  await checkCompatibleProducts(page);
  await expect(page.getByRole('button', { name: 'Refresh current Design' })).toBeVisible();
  await expect(placement).toBeDisabled();
  await page.getByRole('button', { name: 'Refresh current Design' }).click();
  await expect(controls).toHaveAttribute('data-version', '2');
  await expect(placement).toBeEnabled();
  await page.waitForFunction(() => window.__furnitureos?.instances['rug-bed']?.ready
    && window.__furnitureos.instances['rug-bed']?.productId === 'bed-rivet-jonathan-queen-walnut', undefined, { timeout: 60_000 });
});
