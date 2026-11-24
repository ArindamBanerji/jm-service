import { expect, test, type Page } from '@playwright/test'

async function account(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('rgi-api-key', 'first-key')
    localStorage.setItem('rgi-domain', 'alpha')
  })
}

test('changing the key stops remaining CSV batches', async ({ page }) => {
  await account(page)
  let release!: () => void
  const firstBatch = new Promise<void>(resolve => { release = resolve })
  let requested!: () => void
  const started = new Promise<void>(resolve => { requested = resolve })
  const keys: string[] = []
  await page.route('**/v1/label-health/analyze', route => route.fulfill({
    json: { metadata: { row_count: 200, verified_count: 0, factor_count: 2 }, warnings: [] },
  }))
  await page.route('**/v1/labels/ingest/batch', async route => {
    keys.push(route.request().headers()['x-api-key'])
    requested()
    await firstBatch
    try { await route.fulfill({ json: { batch_size: 100, results: [] } }) } catch { /* aborted fetch */ }
  })
  await page.goto('/#/upload')
  const csv = 'label_id,category,factor_a,factor_b\n' +
    Array.from({ length: 200 }, (_, i) => `L${i},A,0.5,0.5`).join('\n')
  await page.locator('input[type=file]').setInputFiles({
    name: 'labels.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  })
  await expect(page.getByText(/Analysis ready/)).toBeVisible()
  await page.getByRole('button', { name: 'Start scoring these labels' }).click()
  await started
  await page.locator('#api-key').fill('second-key')
  await page.locator('#api-key').press('Enter')
  release()
  await expect(page.getByText(/Import stopped: account changed during upload/)).toBeVisible()
  expect(keys).toEqual(['first-key'])
})

test('registration clears previous account domain and checkout state', async ({ page }) => {
  await account(page)
  await page.addInitScript(() => sessionStorage.setItem('dlj-checkout-pending', 'starter'))
  await page.route('**/v1/auth/register', route => route.fulfill({
    status: 201, json: { api_key: 'new-key', tenant_id: 'new', tier: 'trial', message: 'Ready' },
  }))
  await page.goto('/#/signup')
  await page.getByRole('textbox', { name: 'Email' }).fill('new@example.com')
  await page.getByRole('button', { name: 'Start Free Trial' }).click()
  await expect(page.getByLabel('Your API key')).toHaveValue('new-key')
  expect(await page.evaluate(() => [
    localStorage.getItem('rgi-domain'),
    sessionStorage.getItem('dlj-checkout-pending'),
    localStorage.getItem('rgi-api-key'),
  ])).toEqual([null, null, 'new-key'])
})

test('span and tag controls are locked during save', async ({ page }) => {
  await account(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let requested!: () => void
  const started = new Promise<void>(resolve => { requested = resolve })
  await page.route('**/v1/labels/alpha/items/one/relabel', async route => {
    requested()
    await gate
    await route.fulfill({ json: { label_id: 'one', revision_id: 'two', category: 'A', previous_category: null } })
  })
  await page.route('**/v1/labels/alpha/items/one', route => route.fulfill({ json: {
    domain_id: 'alpha', label_id: 'one', category: 'A', annotator_id: null,
    factors: { a: 0.5 }, recommended_action: 'approve', confidence: 0.7,
    text: 'one', actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: 'one', previous_category: null, status: 'scored',
    content: { content_type: 'text_multilabel', tags: ['first'], spans: [], image_url: null },
  } }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [] }))
  await page.route('**/v1/domains/alpha/autonomy', route => route.fulfill({
    json: { categories: [], overall_tier: 'red' },
  }))
  await page.goto('/#/review/one')
  await page.getByRole('combobox', { name: 'Add tag' }).fill('second')
  await page.getByRole('combobox', { name: 'Add tag' }).press('Enter')
  await page.getByRole('button', { name: 'Save Tags' }).click()
  await started
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Remove second' })).toBeDisabled()
  release()
})

test('search invalidates selected queue rows before the next response', async ({ page }) => {
  await account(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let searched!: () => void
  const started = new Promise<void>(resolve => { searched = resolve })
  let writes = 0
  await page.route('**/v1/domains/alpha/autonomy', route => route.fulfill({
    json: { categories: [], overall_tier: 'red' },
  }))
  await page.route('**/v1/labels/alpha/pending*', async route => {
    if (new URL(route.request().url()).searchParams.has('search')) {
      searched()
      await gate
      return route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } })
    }
    return route.fulfill({ json: [{
      label_id: 'old', category: 'A', annotator_id: null, confidence: 0.7,
      recommended_action: 'approve', text_preview: 'old',
    }], headers: { 'X-Total-Count': '1' } })
  })
  await page.route('**/v1/labels/alpha/bulk-verify', route => {
    writes++
    return route.fulfill({ json: { processed: 1, skipped: 0, errors: [] } })
  })
  await page.goto('/#/queue')
  await page.getByRole('checkbox', { name: 'Select old' }).check()
  await page.getByRole('searchbox', { name: 'Search labels' }).fill('new')
  await started
  await expect(page.getByRole('region', { name: 'Bulk review actions' })).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: 'Select old' })).toHaveCount(0)
  expect(writes).toBe(0)
  release()
})

test('HTML account success produces an error instead of crashing Settings', async ({ page }) => {
  await account(page)
  await page.route('**/v1/account', route => route.fulfill({
    status: 200, contentType: 'text/html', body: '<html>proxy fallback</html>',
  }))
  await page.route('**/v1/account/domains', route => route.fulfill({ json: [] }))
  await page.route('**/v1/domains/alpha/guidelines', route => route.fulfill({ json: { guidelines: '' } }))
  await page.goto('/#/settings')
  await expect(page.getByRole('alert')).toContainText('Unexpected response format')
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
})
