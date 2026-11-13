import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests against the real stack: the Angular dev server (npm start), the API,
 * the worker, the outbox relay and the mock services must already be running (see
 * docs/25-frontend.md, section 12). Each test signs up its own user and organization
 * through the API, so runs do not depend on, or disturb, existing data.
 */
export default defineConfig({
  testDir: './tests',
  outputDir: './results',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // the tests share one backend, worker and set of mocks
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: './report', open: 'never' }]],
  use: {
    baseURL: process.env['SF_WEB'] ?? 'http://localhost:4200',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
    ...devices['Desktop Chrome'],
    launchOptions: process.env['SF_CHROME'] ? { executablePath: process.env['SF_CHROME'] } : {},
  },
});
