import { expect, test, type Page } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { uploadWalls } from './capture-fixture';

type StreamReceipt = { url: string; status: number; body: string; error?: string };
declare global { interface Window { __readinessStreams: StreamReceipt[] } }

test.skip(process.env.E2E_FINAL_READINESS_PROOF !== '1', 'Requires the explicit offline final proof server with the real expanded Catalogue and local PostgreSQL.');

const expansionProductIds = new Set<string>();
test.beforeAll(async () => {
  const folder = 'api/catalogue/providers/expansion';
  const index = JSON.parse(await readFile(join(folder, 'index.json'), 'utf8'));
  for (const digest of index.batches) {
    const batch = JSON.parse(await readFile(join(folder, `${digest}.json`), 'utf8'));
    for (const entry of batch.entries) expansionProductIds.add(entry.record.productId);
  }
  expect(expansionProductIds.size).toBe(292);
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const proof = window;
    proof.__readinessStreams = [];
    const original = window.fetch.bind(window);
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const response = await original(...args);
      const input = args[0];
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, location.href).pathname.endsWith('/variants')) {
        // Observe the real stream before CDP discards its consumed response body.
        void response.clone().text().then(body => proof.__readinessStreams.push({ url, status: response.status, body }))
          .catch(error => proof.__readinessStreams.push({ url, status: response.status, body: '', error: String(error) }));
      }
      return response;
    };
  });
  await page.route('https://local-saved.invalid/auth/v1/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `http://127.0.0.1:55469${url.pathname}${url.search}` });
    await route.fulfill({ response });
  });
});

async function generateEvents(page: Page) {
  const before = await page.evaluate(() => window.__readinessStreams.length);
  await page.getByRole('button', { name: 'Generate confirmed Room', exact: true }).click();
  await page.waitForFunction(count => window.__readinessStreams.length > count, before, { timeout: 290_000 });
  const receipt = await page.evaluate(index => window.__readinessStreams[index]!, before);
  expect(receipt.status).toBe(200); expect(receipt.error).toBeUndefined();
  return receipt.body.trim().split('\n').map(line => JSON.parse(line));
}

async function rendered(page: Page, ids: string[]) {
  await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();
  try {
    await page.waitForFunction(ids => ids.every(id => {
      const p = window.__furnitureos?.instances[id];
      return p?.actualFrameRendered && p.renderedMeshCount > 0 && p.ready;
    }), ids, { timeout: 90_000 });
  } catch (error) {
    await test.info().attach('actual-scene-at-render-failure', {
      body: JSON.stringify(await page.evaluate(() => ({ scene: window.__furnitureos,
        canvas: document.querySelector('canvas')?.getBoundingClientRect().toJSON(),
        stage: document.querySelector('[data-testid="stage"]')?.getBoundingClientRect().toJSON() }))),
      contentType: 'application/json',
    });
    throw error;
  }
}

async function nudge(page: Page, id: string) {
  await page.getByRole('combobox', { name: 'Placement to Nudge' }).selectOption(id);
  await page.getByRole('button', { name: /Prepare Nudge|Retry Nudge/ }).click();
  await expect(page.getByTestId('nudge-controls')).toHaveAttribute('data-state', 'ready');
  await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();
  const box = (await page.getByTestId('room-canvas').locator('canvas').boundingBox())!;
  const points = await page.evaluate(id => window.__furnitureos!.instances[id]!.screenPoints ?? [], id);
  for (const [x, y] of points) {
    const point = { x: box.x + (x + 1) * box.width / 2, y: box.y + (1 - y) * box.height / 2 };
    await page.mouse.move(point.x, point.y); await page.mouse.down();
    await page.waitForTimeout(100);
    const state = await page.getByTestId('nudge-controls').getAttribute('data-state');
    if (state === 'dragging' || state === 'clamped') {
      const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/nudges' && r.request().method() === 'POST');
      await page.mouse.move(point.x + 8, point.y + 5, { steps: 5 }); await page.mouse.up();
      const result = await (await response).json(); expect(result.status).toBe('accepted'); return result;
    }
    await page.mouse.up();
  }
  throw new Error('No actual Mesh point started an accepted Nudge.');
}

async function publisherDisclosure(page: Page, historicalNote: string) {
  const current = page.getByTestId('publisher-license-current').first();
  await expect(current).toBeVisible();
  await expect(current).toContainText('all asset licenses changed from CC BY-NC to CC BY in 2023');
  await expect(current.getByRole('link', { name: "ABO publisher's AWS Registry entry" })).toHaveAttribute('href', 'https://registry.opendata.aws/amazon-berkeley-objects/');
  const history = page.getByTestId('historical-license-records').first();
  await expect(history.locator('p').last()).not.toBeVisible();
  const summary = history.locator('summary');
  await summary.focus(); await summary.press('Enter');
  await expect(history).toContainText(historicalNote);
  await expect(history.getByTestId('license-conflict')).toBeVisible();
  await summary.press('Enter');
  await expect(history.getByTestId('license-conflict')).not.toBeVisible();
}

for (const shape of ['Rectangle', 'L-shaped'] as const) test(`actual expanded ${shape} Bedroom capture, mutation and durable restore`, async ({ page, request }) => {
  test.setTimeout(600_000);
  await request.post('/__controlled/mode', { data: { mode: 'normal' } });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/capture');
  await page.getByRole('checkbox', { name: /I understand private photo/ }).check();
  await page.getByRole('button', { name: 'Create private Capture' }).click();
  await page.getByRole('radio', { name: 'Bedroom', exact: true }).check();
  await page.getByRole('radio', { name: shape, exact: true }).check();
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  await uploadWalls(page, shape === 'Rectangle' ? ['A', 'B', 'C', 'D'] : ['A', 'B', 'C', 'D', 'E', 'F']);
  const dimensions = shape === 'Rectangle' ? [['Width (Wall A / C)', '10'], ['Depth (Wall B / D)', '10']] : [['Overall width', '10'], ['Overall depth', '10'], ['Notch width', '2'], ['Notch depth', '2']];
  for (const [label, value] of [...dimensions, ['Ceiling height', '3']]) await page.getByLabel(label!, { exact: true }).fill(value!);
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  for (const wall of shape === 'Rectangle' ? 'ABCD' : 'ABCDEF') await page.getByRole('checkbox', { name: `I reviewed every Opening on Wall ${wall}, including if there are none.`, exact: true }).check();
  await page.getByRole('checkbox', { name: /I checked and confirm all (three|five)/ }).check();
  await page.getByRole('checkbox', { name: 'I acknowledge the empty-Room assumption.' }).check();
  const confirmation = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/confirm') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Review and confirm Room', exact: true }).click();
  const capture = (await (await confirmation).json()).capture;
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  const events = await generateEvents(page);
  const variants = events.filter(e => e.type === 'variant');
  expect(variants.length).toBeGreaterThanOrEqual(2);
  expect(new Set(variants.map(e => e.signature)).size).toBe(variants.length);
  const design = variants[0].result.design;
  const retained = design.products.filter((p: { id: string }) => design.placements.some((v: { productId: string }) => v.productId === p.id));
  expect([...new Set(retained.filter((p: { category: string }) => !['bed', 'rug'].includes(p.category)).map((p: { category: string }) => p.category))]).toEqual(expect.arrayContaining(['nightstand', 'chair', 'lamp']));
  expect(retained.filter((p: { id: string }) => expansionProductIds.has(p.id)).length).toBeGreaterThanOrEqual(4);
  await expect(page.getByRole('heading', { name: 'Validated furnished Room' })).toBeVisible();
  await page.getByRole('button', { name: /^Variant A/ }).click();
  const ids = design.placements.map((p: { instanceId: string }) => p.instanceId);
  await rendered(page, ids);
  await expect(page.getByText('Meshes are approximate representations of Products.', { exact: false })).toBeVisible();
  await publisherDisclosure(page, retained[0].attribution.licenseNote);
  await page.getByRole('combobox', { name: 'Placement to Swap' }).selectOption('optional-chair');
  const candidateStart = Date.now();
  // The entire private operation must finish within its existing120s Capture
  // lease. A longer browser wait cannot turn lease expiry into acceptance.
  const candidateResponse = page.waitForResponse(r => /\/api\/swaps\/[^/]+\/candidates$/.test(new URL(r.url()).pathname), { timeout: 120_000 });
  await page.getByRole('button', { name: 'Check compatible Products', exact: true }).click();
  const compatible = await (await candidateResponse).json();
  const candidateDurationMs = Date.now() - candidateStart;
  expect(compatible.status).toBe('candidates'); expect(compatible.candidates.length).toBeGreaterThan(0);
  await expect(page.getByRole('combobox', { name: 'Compatible Product' })).toBeVisible();
  const swapStart = Date.now();
  const swapped = page.waitForResponse(r => new URL(r.url()).pathname === '/api/swaps' && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Swap Product', exact: true }).click();
  const acceptedSwap = await (await swapped).json(); expect(acceptedSwap.status).toBe('accepted');
  const swapDurationMs = Date.now() - swapStart;
  const nudgeStart = Date.now();
  // Nudge the actual just-swapped native chair. The bed can honestly have no
  // conservative attachment; this flow still requires an accepted real drag.
  const acceptedNudge = await nudge(page, 'optional-chair');
  const nudgeDurationMs = Date.now() - nudgeStart;
  expect(acceptedNudge.design.swap.version).toBeGreaterThan(acceptedSwap.design.swap.version);
  const swappedChair = acceptedSwap.design.placements.find((p: { instanceId: string }) => p.instanceId === 'optional-chair');
  const nudgedChair = acceptedNudge.design.placements.find((p: { instanceId: string }) => p.instanceId === 'optional-chair');
  expect(nudgedChair.position).not.toEqual(swappedChair.position);
  expect(nudgedChair.yaw).toBe(swappedChair.yaw);
  expect(nudgedChair.position[1]).toBe(swappedChair.position[1]);
  await page.getByRole('checkbox', { name: 'I agree to retain this Design' }).check();
  await page.getByRole('button', { name: 'Save Design', exact: true }).click();
  const archiveResponse = page.waitForResponse(r => /\/api\/saved-designs\/[^/]+$/.test(new URL(r.url()).pathname) && !r.url().endsWith('/config') && r.request().method() === 'GET');
  await page.getByRole('link', { name: 'Open saved Design' }).click();
  const archive = await (await archiveResponse).json();
  expect(archive.design.placements).toEqual(acceptedNudge.design.placements);
  const owner = await page.evaluate(() => JSON.parse(localStorage.getItem('sb-local-saved-auth-token')!).user.id);
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(`readiness-${shape.toLowerCase()}-${crypto.randomUUID()}@example.test`);
  await page.getByRole('button', { name: 'Link email to this account' }).click();
  await page.getByRole('textbox', { name: 'Email verification code' }).fill('123456');
  await page.getByRole('button', { name: 'Verify email code' }).click();
  await expect(page.getByText('Email linked and refreshed.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('sb-local-saved-auth-token')!).user.id)).toBe(owner);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Reopened Design' })).toBeVisible();
  await rendered(page, ids);
  await expect(page.getByText('Meshes are approximate representations of Products.', { exact: false })).toBeVisible();
  await publisherDisclosure(page, archive.design.products[0].attribution.licenseNote);
  const root = process.env.FURNITUREOS_EVIDENCE_DIR!; await mkdir(root, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await rendered(page, ids);
    await expect(page.getByTestId('publisher-license-current').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: join(root, `expanded-${shape}-${width}.png`), fullPage: true });
  }
  await writeFile(join(root, `expanded-${shape}.json`), JSON.stringify({ scope: 'Controlled external Auth/Storage/provider; actual source Catalogue/core/PostgreSQL; no hosted/owner/paid evidence', capture, events, compatible, candidateDurationMs, acceptedSwap, swapDurationMs, acceptedNudge, nudgeInstanceId: 'optional-chair', nudgeDurationMs, archive, frame: await page.evaluate(() => window.__furnitureos) }, null, 2));
});

for (const shape of ['Rectangle', 'L-shaped'] as const) test(`actual expanded ${shape} Living anchors and honest partial Variants`, async ({ page, request }) => {
  test.setTimeout(300_000);
  await request.post('/__controlled/mode', { data: { mode: 'normal' } });
  await page.goto('/capture');
  await page.getByRole('checkbox', { name: /I understand private photo/ }).check();
  await page.getByRole('button', { name: 'Create private Capture' }).click();
  await page.getByRole('radio', { name: 'Living room', exact: true }).check();
  await page.getByRole('radio', { name: shape, exact: true }).check();
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  await uploadWalls(page, shape === 'Rectangle' ? ['A', 'B', 'C', 'D'] : ['A', 'B', 'C', 'D', 'E', 'F']);
  const dimensions = shape === 'Rectangle' ? [['Width (Wall A / C)', '10'], ['Depth (Wall B / D)', '10']] : [['Overall width', '10'], ['Overall depth', '10'], ['Notch width', '2'], ['Notch depth', '2']];
  for (const [label, value] of [...dimensions, ['Ceiling height', '3']]) await page.getByLabel(label!, { exact: true }).fill(value!);
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  for (const wall of shape === 'Rectangle' ? 'ABCD' : 'ABCDEF') await page.getByRole('checkbox', { name: `I reviewed every Opening on Wall ${wall}, including if there are none.`, exact: true }).check();
  await page.getByRole('checkbox', { name: /I checked and confirm all (three|five)/ }).check();
  await page.getByRole('checkbox', { name: 'I acknowledge the empty-Room assumption.' }).check();
  await page.getByRole('button', { name: 'Review and confirm Room', exact: true }).click();
  await page.getByRole('radio', { name: 'Soft neutrals and warm wood' }).check();
  const events = await generateEvents(page);
  const variants = events.filter(e => e.type === 'variant');
  expect(variants.length).toBeGreaterThanOrEqual(2);
  expect(new Set(variants.map(e => e.signature)).size).toBe(variants.length);
  const design = variants[0].result.design;
  expect(new Set(design.products.map((p: { category: string }) => p.category))).toEqual(new Set(['sofa', 'table', 'chair']));
  expect(design.products.every((p: { id: string }) => p.id.startsWith('abo-'))).toBe(true);
  expect(design.products.some((p: { id: string }) => expansionProductIds.has(p.id))).toBe(true);
  const ids = design.placements.map((p: { instanceId: string }) => p.instanceId);
  await expect(page.getByRole('heading', { name: 'Validated furnished Room' })).toBeVisible();
  await page.getByRole('button', { name: /^Variant A/ }).click();
  const root = process.env.FURNITUREOS_EVIDENCE_DIR!; await mkdir(root, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await rendered(page, ids);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: join(root, `expanded-Living-${shape}-${width}.png`), fullPage: true });
  }
  await request.post('/__controlled/mode', { data: { mode: 'partial' } });
  const partial = await generateEvents(page);
  expect(partial.filter(e => e.type === 'variant')).toHaveLength(1);
  expect(partial.at(-1)).toMatchObject({ type: 'complete', status: 'partial', available: ['A'], reason: 'duplicate-exhausted' });
  await expect(page.getByRole('heading', { name: 'Validated furnished Room' })).toBeVisible();
  await rendered(page, ids);
  await writeFile(join(root, `expanded-Living-${shape}.json`), JSON.stringify({ scope: 'Controlled provider; unchanged real expanded Catalogue, Capture authority and local PostgreSQL. Not owner/paid/hosted evidence', events, partial, frame: await page.evaluate(() => window.__furnitureos) }, null, 2));
  await request.post('/__controlled/mode', { data: { mode: 'normal' } });
});
