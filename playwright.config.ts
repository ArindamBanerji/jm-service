import { defineConfig } from '@playwright/test';

const port = process.env.DLJ_PORT || '8080';

export default defineConfig({
  testDir: '.',
  testMatch: ['e2e/**/*.spec.ts', 'tests/e2e/**/*.spec.ts'],
  timeout: 30_000,
  retries: 0,
  workers: 2,
  use: {
    baseURL: `http://localhost:${port}`,
    headless: true,
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'dlj', use: {} },
  ],
});
