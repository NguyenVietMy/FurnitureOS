import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import os from 'node:os';

const evidence = process.env.CURATOR_EVIDENCE_DIR ?? path.join(os.tmpdir(), `furnitureos-curator-browser-${Date.now()}`);
export default defineConfig({
  testDir: './tests', testMatch: '**/*.spec.ts', workers: 1, fullyParallel: false,
  timeout: 120_000, expect: { timeout: 30_000 }, retries: 0,
  outputDir: path.join(evidence, 'playwright-output'), reporter: [['list']],
  use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure', launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] } },
});
