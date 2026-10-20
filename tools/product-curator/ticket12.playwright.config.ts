import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
const evidence = process.env.CURATOR_EVIDENCE_DIR;
if (!evidence || !process.env.E2E_BASE_URL) throw new Error('Explicit controlled server and fresh external evidence directory required');
export default defineConfig({
  testDir: '../../e2e', testMatch: 'living-controlled.fixture.ts', workers: 1, fullyParallel: false,
  timeout: 120_000, expect: { timeout: 30_000 }, retries: 0,
  outputDir: path.join(evidence, 'playwright-output'), reporter: [['list']],
  use: { ...devices['Desktop Chrome'], baseURL: process.env.E2E_BASE_URL, trace: 'retain-on-failure', launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] } },
});
