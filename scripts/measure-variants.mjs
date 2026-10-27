/** Frozen future live timing collector. NEVER run without separate owner authorization. */
import { chromium } from '@playwright/test';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { installVariantObservation } from './variant-measurement-observer.mjs';
import { createTimingEvidence } from './variant-timing-evidence.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const args = process.argv.slice(2);
const value = flag => args[args.indexOf(flag) + 1];
if (!args.includes('--authorized-paid') || !args.includes('--config') || !args.includes('--output')) {
  throw new Error('Future owner gate: --authorized-paid --config EXTERNAL.json --output EXTERNAL-DIRECTORY are required. This tool initiates ten paid batches.');
}
const output = resolve(value('--output')), configPath = resolve(value('--config'));
for (const path of [output, configPath]) {
  const rel = relative(root, path);
  if (!rel || (!rel.startsWith('..') && !isAbsolute(rel))) throw new Error('Timing configuration and evidence must be outside Git.');
}
const config = JSON.parse(readFileSync(configPath, 'utf8'));
if (config.protocol !== 'ticket-14-live-timing-v1' || !config.baseUrl || !config.machine || !config.serverSourceSha256 || config.referenceId !== 'ref-01') throw new Error('Incomplete frozen configuration.');
const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: root }).toString('utf8').split('\0').filter(Boolean).sort();
const records = files.map(path => ({ path, sha256: createHash('sha256').update(readFileSync(resolve(root, path))).digest('hex') }));
const sourceSha256 = createHash('sha256').update(JSON.stringify(records)).digest('hex');
if (sourceSha256 !== config.serverSourceSha256) throw new Error('The source differs from the owner-frozen server fingerprint.');
// A fresh directory and exclusive files preserve every previous failed attempt.
const save = createTimingEvidence(output);
save('freeze.json', { config, sourceSha256, records, viewport: { width: 390, height: 844 }, network: { latencyMs: 150, downloadBytesPerSecond: 1_125_000, uploadBytesPerSecond: 125_000 }, runsPerRoomType: 5, provider: 'claude-opus-5', physicalPhone: 'WAIVED', automaticRetries: 0 });
let browser;
try {
  browser = await chromium.launch();
  for (const roomType of ['bedroom', 'living-room']) for (let run = 1; run <= 5; run++) {
    const record = { protocol: config.protocol, sourceSha256, roomType, run, referenceId: config.referenceId, startedAt: new Date().toISOString(), measurement: null, measuredUsage: null, outcome: null, collectionError: null };
    save(`${roomType}-${run}.started.json`, record);
    let context;
    try {
    context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    await context.addInitScript(installVariantObservation);
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1_125_000, uploadThroughput: 125_000 });
    await page.goto(new URL('/design/live', config.baseUrl).href);
    await page.getByRole('radio', { name: roomType === 'bedroom' ? 'Bedroom' : 'Living room', exact: true }).check();
    await page.locator('input[name="reference-image"][value="ref-01"]').check();
    await page.getByRole('button', { name: roomType === 'bedroom' ? 'Generate bedroom' : 'Generate living room', exact: true }).click();
    let measurement;
    try {
      await page.waitForFunction(() => window.__furnitureos?.generationId?.endsWith(':A') && window.__furnitureos.usefulView.status === 'complete', undefined, { timeout: 305_000 });
      measurement = await page.evaluate(() => ({ generateAtMs: window.__variantGenerateAt, firstFurnishedAtMs: window.__furnitureos.usefulView.completedAtMs, generationId: window.__furnitureos.generationId }));
      measurement.durationMs = measurement.firstFurnishedAtMs - measurement.generateAtMs;
      measurement.under30Seconds = measurement.durationMs < 30_000;
    } catch { measurement = { under30Seconds: false, failure: 'No furnished A within the request ceiling.' }; }
    record.measurement = measurement;
    await page.waitForFunction(() => window.__variantWire?.done, undefined, { timeout: 305_000 });
    const observed = await page.evaluate(() => window.__variantWire);
    record.outcome = observed.outcome;
    record.measuredUsage = observed.outcome?.usage ?? null;
    record.collectionError = observed.error;
    } catch (error) { record.collectionError = String(error); }
    finally {
      record.finishedAt = new Date().toISOString();
      save(`${roomType}-${run}.json`, record);
      await context?.close();
    }
  }
} catch (error) {
  save('collection-failure.json', { at: new Date().toISOString(), error: String(error) });
  throw error;
} finally { await browser?.close(); }
