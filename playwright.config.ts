import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 3101);
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;
const trustedOidcToken = process.env.VERCEL_OIDC_TOKEN;

/**
 * The browser proof runs against a production build, not the dev server: it is
 * the built output that gets deployed, and asset URLs, caching headers and
 * bundling all differ in dev.
 *
 * Headless Chromium has no GPU here, so WebGL is served by SwiftShader. Recent
 * Chromium requires the software path to be opted into explicitly.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  workers: 2,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    extraHTTPHeaders: trustedOidcToken
      ? { 'x-vercel-trusted-oidc-idp-token': trustedOidcToken }
      : undefined,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        launchOptions: {
          args: [
            '--use-gl=angle',
            '--use-angle=swiftshader',
            '--enable-unsafe-swiftshader',
            '--ignore-gpu-blocklist',
          ],
        },
      },
    },
  ],
});
