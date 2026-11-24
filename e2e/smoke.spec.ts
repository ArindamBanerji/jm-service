import { test, expect } from '@playwright/test';

test('health endpoint returns valid JSON', async ({ request }) => {
  const res = await request.get('/v1/health');
  const body = await res.json();
  // Server is up and returns structured health info.
  // Status may be "unhealthy" without a local DB — that's expected in dev.
  expect(body).toHaveProperty('status');
  expect(body).toHaveProperty('version');
  expect(body).toHaveProperty('checks');
});

test('frontend loads', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).not.toBeEmpty();
});

test('upload screen renders', async ({ page }) => {
  await page.goto('/#/upload');
  await expect(page.locator('text=/upload|drop|csv/i').first()).toBeVisible();
});

test('queue screen renders', async ({ page }) => {
  await page.goto('/#/queue');
  await page.waitForTimeout(1000);
  await expect(page.locator('text=/queue|scored|labels|no data/i').first()).toBeVisible();
});

test('dashboard screen renders', async ({ page }) => {
  await page.goto('/#/dashboard');
  await expect(page.locator('text=/accuracy|verified|dashboard/i').first()).toBeVisible();
});

test('annotators screen renders', async ({ page }) => {
  await page.goto('/#/annotators');
  await expect(page.locator('text=/annotator|profile/i').first()).toBeVisible();
});

test('health report screen renders', async ({ page }) => {
  await page.goto('/#/health');
  await expect(page.locator('text=/health|report|upload|csv/i').first()).toBeVisible();
});
