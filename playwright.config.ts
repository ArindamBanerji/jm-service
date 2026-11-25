import { defineConfig } from '@playwright/test';

const port = process.env.DLJ_PORT || '8080';

export default defineConfig({
  testDir: './e2e',
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
