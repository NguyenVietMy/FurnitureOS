import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium, test } from '@playwright/test';

const shots = join(process.cwd(), 'test-results', 'screenshots');
mkdirSync(shots, { recursive: true });
test('fresh desktop, mobile, tablet and full-page landing evidence', async ({ baseURL, extraHTTPHeaders }) => {
  // Isolate capture from the project's SwiftShader launch flags: very tall
  // screenshots can repeat compositor tiles with that WebGL configuration.
  const browser = await chromium.launch({ args: ['--disable-gpu'] });
  try {
    const page = await browser.newPage({ extraHTTPHeaders });
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }, { width: 768, height: 1024 }]) {
      await page.setViewportSize(viewport);
      await page.goto(baseURL!);
      await page.evaluate(async () => {
        await document.fonts.ready;
        await Promise.all([...document.images].map((image) => { image.loading = 'eager'; return image.decode(); }));
        await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      });
      await page.screenshot({ path: join(shots, `landing-${viewport.width}.png`) });
      if (viewport.width === 1440) await page.screenshot({ path: join(shots, 'landing-full.png'), fullPage: true });
    }
  } finally { await browser.close(); }
});
