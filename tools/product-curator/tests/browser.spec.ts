import { test, expect, type Page } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
// Node-side integration harness; no control API or fixture mode is exposed by CLI/HTTP.
// @ts-expect-error JavaScript local server has its own runtime contract tests.
import { createCurator } from '../server.mjs';
// @ts-expect-error Explicit controlled published-byte fixtures, never native/owner evidence.
import { evidenceDir, controlledRunner, controlledBarrier, lamp } from './helpers.mjs';

type App = Awaited<ReturnType<typeof createCurator>>;
let app: App, owner: App, root: string;
let ownerBarrier: ReturnType<typeof controlledBarrier>, ownerNow = 10000;
const errors: string[] = [];
async function post(page: Page, data: Record<string, unknown>) {
  return page.evaluate(async (operation) => {
    const state = await (await fetch('/api/state')).json();
    const r = await fetch('/api/mutate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Curator-Token': state.token }, body: JSON.stringify({ ...operation, revision: state.revision, opId: crypto.randomUUID() }) });
    return { status: r.status, body: await r.json() };
  }, data);
}
async function state(page: Page) { return page.evaluate(async () => (await fetch('/api/state')).json()); }
async function drawn(page: Page, expected?: string) {
  await expect.poll(async () => page.evaluate((url) => window.__curatorDraws?.some((d) => url ? d.url === url : d.meshes > 0) ?? false, expected)).toBe(true);
}
async function keyboard(page: Page, key: string) {
  await page.locator('h1').click();
  const before = (await state(page)).revision;
  await page.keyboard.press(key);
  await expect.poll(async () => (await state(page)).revision).toBeGreaterThan(before);
  await expect.poll(async () => page.getByRole('button', { name: '[ Previous', exact: true }).isEnabled()).toBe(true);
}
test.beforeAll(async () => {
  root = await evidenceDir('browser-CONTROLLED');
  app = await createCurator({ stateDir: path.join(root, 'automated'), actor: 'automated', runner: controlledRunner({ failFirst: true, delay: 1500 }) });
  ownerBarrier = controlledBarrier();
  owner = await createCurator({ stateDir: path.join(root, 'owner-state-CONTROLLED'), actor: 'owner', controlled: true, clock: () => ownerNow, runner: controlledRunner({ barrier: ownerBarrier }) });
});
test.afterAll(async () => {
  ownerBarrier?.release();
  await writeFile(path.join(root, 'BROWSER-EVIDENCE.json'), JSON.stringify({ kind: 'controlled-automated-browser-evidence', realOwnerSample: 'UNRUN', errors }, null, 2));
  await app?.close(); await owner?.close();
});
test.beforeEach(async ({ page }) => {
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(app.origin);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Product curator');
});

test('actual drawn pinned Mesh at desktop, 390 and 768; accessible layout and keyboard viewport', async ({ page }) => {
  const skip = page.getByRole('link', { name: 'Skip to curator content' });
  await expect(skip).toBeVisible();
  await page.keyboard.press('Tab'); await expect(skip).toBeFocused();
  await page.keyboard.press('Enter'); await expect(page.getByRole('main')).toBeFocused();
  await drawn(page);
  expect(await page.locator('h1').count()).toBe(1);
  for (const width of [1440, 390, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.getByRole('region', { name: /Interactive Mesh viewport/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: path.join(root, `actual-mesh-${width}.png`), fullPage: true });
  }
  const revision = (await state(page)).revision;
  const viewport = page.getByRole('region', { name: /Interactive Mesh viewport/ });
  await viewport.focus();
  const originalView = await page.evaluate(() => window.__curatorView!);
  await page.keyboard.press('ArrowRight');
  expect(await page.evaluate(() => window.__curatorView!.position)).not.toEqual(originalView.position);
  const rotated = await page.evaluate(() => window.__curatorView!);
  await viewport.dispatchEvent('keydown', { key: 'ArrowRight', ctrlKey: true, bubbles: true });
  await viewport.dispatchEvent('keydown', { key: 'ArrowRight', repeat: true, bubbles: true });
  expect(await page.evaluate(() => window.__curatorView!.position)).toEqual(rotated.position);
  await page.keyboard.press('0');
  const reset = await page.evaluate(() => window.__curatorView!);
  reset.position.forEach((value, index) => expect(value).toBeCloseTo(originalView.position[index]!, 7));
  const radius = (view: { position: number[]; target: number[] }) => Math.hypot(...view.position.map((v, i) => v - view.target[i]!));
  await page.keyboard.press('+');
  expect(radius(await page.evaluate(() => window.__curatorView!))).toBeLessThan(radius(reset));
  await page.keyboard.press('-'); await page.keyboard.press('ArrowUp'); await page.keyboard.press('0');
  expect((await state(page)).revision).toBe(revision);
  expect(errors).toEqual([]);
});

test('shortcut guards, missing tags, tag/reject/undo keyboard controls and reload persistence', async ({ page }) => {
  const initial = await state(page), before = initial.revision;
  await page.locator('h1').click(); await page.keyboard.press('a');
  await expect(page.getByRole('alert')).toContainText('at least one Style and one Room Type');
  expect((await state(page)).revision).toBe(before);
  await page.getByRole('button', { name: '[ Previous', exact: true }).focus();
  await page.keyboard.press('1');
  await page.locator('h1').dispatchEvent('keydown', { key: '1', repeat: true, bubbles: true });
  await page.locator('h1').dispatchEvent('keydown', { key: '1', ctrlKey: true, bubbles: true });
  await page.evaluate(() => {
    const editable = document.createElement('div'); editable.contentEditable = 'plaintext-only'; document.body.append(editable);
    editable.dispatchEvent(new KeyboardEvent('keydown', { key: '1', bubbles: true })); editable.remove();
  });
  expect((await state(page)).revision).toBe(before);
  await keyboard(page, '1'); await keyboard(page, 'b');
  await page.reload();
  await expect(page.getByRole('checkbox', { checked: true })).toHaveCount(2);
  await keyboard(page, ']'); expect((await state(page)).cursor).toBe(1);
  await keyboard(page, '['); expect((await state(page)).cursor).toBe(0);
  await keyboard(page, 'r'); expect((await state(page)).candidates[0].decision).toBe('rejected');
  await keyboard(page, 'u'); expect((await state(page)).candidates[0].decision).toBe(null);
  expect((await state(page)).cursor).toBe(0);
  await keyboard(page, 'u'); expect((await state(page)).candidates[0].rooms).toEqual([]);
  const checkbox = page.getByRole('checkbox').first();
  await checkbox.focus(); await page.keyboard.press('Space');
  await expect(checkbox).not.toBeChecked();
  await page.getByRole('button', { name: 'Next ]', exact: true }).focus(); await page.keyboard.press('Enter');
  await expect.poll(async () => (await state(page)).cursor).toBe(1);
  await page.reload(); expect((await state(page)).cursor).toBe(1);
  const port = Number(new URL(app.origin).port), dir = app.engine.root;
  await app.close();
  app = await createCurator({ stateDir: dir, actor: 'automated', port, runner: controlledRunner({ failFirst: true, delay: 1500 }) });
  await page.reload();
  expect((await state(page)).cursor).toBe(1);
  expect((await state(page)).candidates[0].styles).toEqual([]);
});

test('preview failure and retry leave decisions and tags unchanged', async ({ page }) => {
  await page.route('**/mesh/original/**/lod0.gltf', (route) => route.abort());
  await page.reload();
  await expect(page.getByRole('status')).toContainText('Mesh preview failed');
  const before = await state(page);
  await page.unroute('**/mesh/original/**/lod0.gltf');
  await page.getByRole('button', { name: 'Retry preview' }).click(); await drawn(page);
  expect((await state(page)).revision).toBe(before.revision);
  expect((await state(page)).candidates).toEqual(before.candidates);
});

test('failure progress/retry, immutable accepted URLs, unique Catalogue and retained prior artifacts', async ({ page }) => {
  const initial = await state(page);
  const index = initial.candidates.findIndex((c: { productId: string }) => c.productId === lamp);
  expect((await post(page, { type: 'navigate', cursor: index })).status).toBe(200);
  await page.reload();
  await keyboard(page, '1'); await keyboard(page, 'l');
  await page.getByRole('button', { name: /^Accept/ }).click();
  await expect(page.getByRole('heading', { name: 'Attempt progress' })).toBeVisible();
  await expect(page.locator('.history')).toContainText('controlled-conversion');
  await expect(page.getByRole('button', { name: /^Undo/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Retry acceptance' })).toBeVisible();
  await page.getByRole('button', { name: 'Retry acceptance' }).click();
  await expect.poll(async () => (await state(page)).candidates[index].decision).toBe('accepted');
  const accepted = (await state(page)).candidates[index], firstUrl = accepted.previewUrl;
  expect(firstUrl).toContain('/mesh/attempt/');
  await post(page, { type: 'navigate', cursor: index }); await page.reload(); await drawn(page, firstUrl);
  const firstBytes = await (await page.request.get(`${app.origin}${firstUrl}`)).body();
  const catalogue = await (await page.request.get(`${app.origin}/api/catalogue?roomType=living-room&privateStyleId=style-01`)).json();
  expect(catalogue).toHaveLength(1); expect(catalogue[0].roomTypes).toEqual(['living-room']);
  await page.getByRole('button', { name: /^Undo/ }).click();
  await expect(page.getByRole('button', { name: /^Accept/ })).toBeEnabled();
  await page.getByRole('button', { name: /^Accept/ }).click();
  await expect.poll(async () => (await state(page)).candidates[index].decision).toBe('accepted');
  await post(page, { type: 'navigate', cursor: index }); await page.reload();
  const secondUrl = (await state(page)).candidates[index].previewUrl;
  expect(secondUrl).not.toBe(firstUrl);
  await drawn(page, secondUrl);
  expect(await (await page.request.get(`${app.origin}${firstUrl}`)).body()).toEqual(firstBytes);
  expect(await (await page.request.get(`${app.origin}${secondUrl}`)).body()).not.toEqual(firstBytes);
  expect(await (await page.request.get(`${app.origin}/api/catalogue`)).json()).toHaveLength(1);
  const report = await (await page.request.get(`${app.origin}/api/report`)).json();
  expect(report.counts.failures).toBe(1); expect(report.counts.retries).toBe(1); expect(report.ownerEvidenceStatus).toBe('UNRUN');
  await page.screenshot({ path: path.join(root, 'accepted-controlled-attempt.png'), fullPage: true });
});

test('multi-tab stale mutation is rejected through browser HTTP boundary', async ({ page, context }) => {
  const other = await context.newPage(); await other.goto(app.origin);
  const old = await state(other);
  expect((await post(page, { type: 'navigate', cursor: 3 })).status).toBe(200);
  const stale = await other.evaluate(async (s) => {
    const r = await fetch('/api/mutate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Curator-Token': s.token }, body: JSON.stringify({ type: 'navigate', cursor: 4, revision: s.revision, opId: crypto.randomUUID() }) });
    return { status: r.status, body: await r.json() };
  }, old);
  expect(stale.status).toBe(409); expect(stale.body.error).toContain('another tab');
  await other.close();
});

test('controlled owner gating, saved estimate reload, denied busy pause, pause covers and restart preserves pause', async ({ page }) => {
  await page.goto(owner.origin);
  await expect(page.getByRole('heading', { name: 'Ready for 20 deliberate decisions' })).toBeVisible();
  expect(await page.locator('canvas').count()).toBe(0);
  const input = page.getByLabel('Remaining candidates (optional)');
  await input.fill('120'); await input.blur();
  await expect.poll(async () => (await state(page)).sample.remainingCandidates).toBe(120);
  await page.reload(); await expect(input).toHaveValue('120');
  const revision = (await state(page)).revision;
  await input.focus(); await input.blur();
  await page.waitForTimeout(1000);
  expect((await state(page)).revision).toBe(revision);
  expect((await state(page)).sample.remainingCandidates).toBe(120);
  await page.getByRole('button', { name: 'Start owner sample' }).click(); await drawn(page);
  const first = (await state(page)).candidates[0];
  const checkedBefore = await page.getByRole('checkbox').count(); expect(checkedBefore).toBe(7);
  expect(await page.getByRole('checkbox', { checked: true }).count()).toBe(0);
  await keyboard(page, '1'); await keyboard(page, 'b');
  await page.getByRole('button', { name: /^Accept/ }).click();
  await ownerBarrier.entered;
  ownerNow += 5000; // Controlled active conversion wait, independent of scheduling.
  await page.getByRole('button', { name: 'Pause sample' }).click();
  await expect(page.getByRole('alert')).toContainText('Cannot pause');
  expect((await state(page)).sample.status).toBe('ACTIVE');
  expect((await state(page)).busy).toBe(true);
  const waiting = await (await page.request.get(`${owner.origin}/api/report`)).json();
  expect(waiting.timing.activeSeconds).toBe(5);
  ownerBarrier.release();
  // The page must display the committed revision before its deliberate Pause.
  await expect(page.getByText(/succeeded · committed/)).toBeVisible();
  ownerNow += 2500;
  await page.getByRole('button', { name: 'Pause sample' }).click();
  await expect(page.getByRole('heading', { name: 'Review is paused' })).toBeVisible();
  expect(await page.locator('canvas').count()).toBe(0);
  const r = await page.request.get(`${owner.origin}${first.previewUrl}`); expect(r.status()).toBe(423);
  const frozen = await state(page); expect(frozen.candidates).toBeUndefined();
  const port = Number(new URL(owner.origin).port), dir = owner.engine.root;
  await owner.close();
  owner = await createCurator({ stateDir: dir, actor: 'owner', controlled: true, port, clock: () => ownerNow, runner: controlledRunner() });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Review is paused' })).toBeVisible();
  await expect(input).toHaveValue('120');
  await page.getByRole('button', { name: 'Resume sample' }).click();
  await expect.poll(async () => (await state(page)).sample.status).toBe('ACTIVE');
  ownerNow += 3000;
  await page.getByRole('button', { name: 'Finish sample' }).click();
  await expect(page.getByRole('alert')).toContainText('20 final decisions');
  const report = await (await page.request.get(`${owner.origin}/api/report`)).json();
  expect(report.ownerEvidenceStatus).toBe('UNRUN'); expect(report.timing.activeSeconds).toBe(10.5);
  expect(report.attempts[0].durationMs).toBe(5000);
  await page.screenshot({ path: path.join(root, 'controlled-owner-active.png'), fullPage: true });
});

test('all-processed state retains navigation, review and undo', async ({ page }) => {
  const current = await state(page);
  for (const candidate of current.candidates) if (!candidate.decision) expect((await post(page, { type: 'reject', productId: candidate.productId })).status).toBe(200);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'All 20 have final decisions' })).toBeVisible();
  await page.getByRole('button', { name: '[ Previous', exact: true }).click();
  await expect(page.getByRole('region', { name: /Interactive Mesh viewport/ })).toBeVisible();
  await page.getByRole('button', { name: /^Undo/ }).click();
  await expect.poll(async () => (await state(page)).candidates.filter((c: { decision: string | null }) => !c.decision).length).toBe(1);
  expect(errors).toEqual([]);
});
