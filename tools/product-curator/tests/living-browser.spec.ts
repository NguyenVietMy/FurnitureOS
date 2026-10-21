import { test, expect } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
// @ts-expect-error Explicit local runtime integration seam.
import { createCurator } from '../server.mjs';
// @ts-expect-error External isolated evidence helper.
import { evidenceDir } from './helpers.mjs';

test('four real immutable living previews draw and orbit in an automated review workspace', async ({ page }) => {
  test.skip(!process.env.TICKET12_PREPARED_DIR, 'Requires the exact task preparations');
  const root = await evidenceDir('living-browser-AUTOMATED');
  const app = await createCurator({ stateDir: path.join(root, 'state'), actor: 'automated', profile: 'living-seed-v1', preparedDir: process.env.TICKET12_PREPARED_DIR, ownerIdentity: 'CONTROLLED-AUTOMATED-NOT-OWNER' });
  const errors: string[] = [], assets: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => { if (r.url().includes('.ktx2')) assets.push(r.url()); });
  try {
    await page.goto(app.origin);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Product curator');
    await expect(page.getByText(/8 frozen candidates/)).toBeVisible();
    await expect(page.locator('.review-reference')).toHaveCount(6);
    const proofs = [];
    for (let cursor = 0; cursor < 4; cursor++) {
      if (cursor) {
        const response = await page.evaluate(async (cursor) => {
          const state = await (await fetch('/api/state')).json();
          return (await fetch('/api/mutate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Curator-Token': state.token }, body: JSON.stringify({ type: 'navigate', cursor, opId: crypto.randomUUID(), revision: state.revision }) })).status;
        }, cursor);
        expect(response).toBe(200);
      }
      const state = await (await page.request.get(`${app.origin}/api/state`)).json();
      const candidate = state.candidates[cursor];
      await expect.poll(() => page.evaluate((url) => window.__curatorDraws?.some(d => d.url === url && d.meshes > 0) ?? false, candidate.previewUrl)).toBe(true);
      const viewport = page.getByRole('region', { name: /Interactive Mesh viewport/ });
      await viewport.focus(); await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight');
      for (const width of [1440, 768, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: path.join(root, `${candidate.productId}-${width}.png`), fullPage: true });
      }
      proofs.push({ candidate, draws: await page.evaluate(() => window.__curatorDraws), view: await page.evaluate(() => window.__curatorView) });
    }
    expect(errors).toEqual([]); expect(assets.length).toBeGreaterThan(0);
    await writeFile(path.join(root, 'AUTOMATED-PREVIEW-PROOF.json'), JSON.stringify({ kind: 'AUTOMATED-NOT-OWNER-NO-DECISIONS', proofs, assets, errors }, null, 2));
  } finally { await app.close(); }
});
