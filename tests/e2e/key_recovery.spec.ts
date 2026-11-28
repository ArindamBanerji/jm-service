import { expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { open, project, seed, test } from './release_fixture'

test('clicking the masked key copies the current credential and leaves it masked', async ({ page, server, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: server.url })
  await open(page, server, 'projects')
  const field = page.locator('#api-key')
  await expect(field).toHaveAttribute('type', 'password')
  await field.click()
  await expect(page.getByRole('status').filter({ hasText: /^Copied$/ })).toBeVisible()
  expect(await page.evaluate(async () => await navigator.clipboard.readText() === localStorage.getItem('rgi-api-key'))).toBe(true)
  await expect(field).toHaveAttribute('type', 'password')
})

test('denied clipboard allows manual copy and conceals the key on navigation', async ({ page, server }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: async () => { throw new DOMException('Denied', 'NotAllowedError') } },
  }))
  await open(page, server, 'projects')
  await page.getByRole('button', { name: 'Copy API key' }).click()
  await expect(page.getByText('Key selected. Choose Show to copy manually.')).toBeVisible()
  const field = page.locator('#api-key')
  await page.getByRole('button', { name: 'Show API key' }).click()
  await expect(field).toBeFocused()
  expect(await field.evaluate((input: HTMLInputElement) => input.type === 'text' &&
    input.selectionStart === 0 && input.selectionEnd === input.value.length)).toBe(true)
  await page.getByRole('link', { name: 'Docs', exact: true }).first().click()
  await expect(field).toHaveAttribute('type', 'password')
})

test('a recovery link accepts a code and lets the user retry an expired code', async ({ page, server }) => {
  await open(page, server, 'signup?recover=1')
  await expect(page.getByRole('heading', { name: 'Recover your API key' })).toBeVisible()
  await page.getByRole('button', { name: 'I already have a code' }).click()
  await page.getByLabel('Recovery code').fill('0'.repeat(64))
  await page.getByRole('button', { name: 'Replace API key' }).click()
  await expect(page.getByText('Invalid or expired recovery code')).toBeVisible()
  await page.getByRole('button', { name: 'Request another code' }).click()
  await expect(page.getByRole('button', { name: 'Recover your key' })).toBeVisible()
})

test('a label remains reviewable when tier information is unavailable', async ({ page, server }) => {
  const { id } = await project(page, server)
  await seed(page, server, id)
  await page.route('**/autonomy*', route => route.fulfill({ status: 503, body: 'Unavailable' }))
  await open(page, server, 'projects/' + id + '/review/release-0')
  await expect(page.getByLabel('Known outcome')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Source text' })).toContainText('Release sample 0')
})

test('default project factors accept the first CSV upload', async ({ page, server }) => {
  await open(page, server, 'projects')
  const name = 'first-' + randomUUID()
  await page.getByLabel('Project name').fill(name)
  await page.getByLabel('Public ID').fill(name)
  const factors = page.getByLabel('Factors, comma separated')
  const defaults = await factors.inputValue()
  await factors.fill('quality')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page.getByText('Enter 2–20 distinct factor names, separated by commas.')).toBeVisible()
  await factors.fill(defaults)
  const created = page.waitForResponse(r => r.url().endsWith('/v1/projects') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create project' }).click()
  const response = await created
  expect(response.status()).toBe(201)
  const { id } = await response.json()
  await open(page, server, 'projects/' + id + '/upload')
  const csv = 'label_id,category,verified_outcome,factor_quality,factor_difficulty,text\n' +
    'review-1,default,true,0.8,0.2,First label\nreview-2,default,false,0.3,0.5,Second label'
  await page.locator('input[type=file]').setInputFiles({ name: 'first.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  const scored = page.waitForResponse(r => new URL(r.url()).pathname === '/v1/projects/' + id + '/labels/batch')
  await page.getByRole('button', { name: 'Start scoring these labels' }).click()
  expect((await (await scored).json()).batch_size).toBe(2)
})

test('account usage remains visible when the domain list fails', async ({ page, server }) => {
  await page.route('**/v1/account/domains*', route => route.fulfill({ status: 503, body: 'Unavailable' }))
  await open(page, server, 'settings')
  await expect(page.getByText('The domain list could not be loaded. Use Refresh account to retry.')).toBeVisible()
  await expect(page.getByRole('button', { name: /Upgrade with Paddle/i })).toBeVisible()
})
