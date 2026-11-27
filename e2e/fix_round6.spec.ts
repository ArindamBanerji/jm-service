import { expect, test, type Page } from '@playwright/test'

async function account(page: Page) {
  await page.addInitScript(() => { localStorage.setItem('rgi-api-key', 'key-A'); localStorage.setItem('rgi-domain', 'alpha') })
}

test('Save Tags keeps the next typed tag and blocks verification of it', async ({ page }) => {
  await account(page)
  const base = { domain_id: 'alpha', label_id: 'item-1', category: 'A', annotator_id: null,
    factors: { confidence: .8 }, recommended_action: 'approve', confidence: .8,
    text: 'Source text', actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: 'rev-1', previous_category: null, status: 'scored',
    content: { content_type: 'text_multilabel', spans: [], tags: ['positive'], image_url: null } }
  const successor = { ...base, label_id: 'item-2', revision_id: 'rev-2',
    content: { ...base.content, tags: ['positive', 'urgent'] } }
  let saved = false
  await page.route('**/v1/domains/alpha/autonomy', route => route.fulfill({ json: { domain_id: 'alpha', overall_tier: 'amber', categories: [{ category: 'A', tier: 'amber', verified_count: 0, accuracy: null, conservation_gate_pass: true, conservation_reason: null }] } }))
  await page.route('**/v1/domains/alpha/guidelines', route => route.fulfill({ json: { guidelines: '' } }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } }))
  await page.route('**/v1/labels/alpha/items/item-1', route => route.fulfill({ json: saved ? successor : base }))
  await page.route('**/v1/labels/alpha/items/item-2', route => route.fulfill({ json: successor }))
  await page.route('**/v1/labels/alpha/items/item-1/relabel', route => { saved = true; return route.fulfill({ json: { label_id: 'item-1', revision_id: 'rev-2', category: 'A' } }) })
  await page.goto('/#/review/item-1')
  await expect(page.getByRole('heading', { name: 'item-1' })).toBeVisible()
  const input = page.getByRole('combobox', { name: 'Add tag' })
  await input.fill('urgent'); await input.press('Enter')
  await input.fill('important')
  await page.getByRole('button', { name: 'Save Tags' }).click()
  await expect(page).toHaveURL(/#\/review\/item-2$/)
  await expect(page.getByRole('heading', { name: 'item-2' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toHaveValue('important')
  await expect(page.getByRole('button', { name: 'Remove urgent' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct')
  await expect(page.getByRole('button', { name: 'Approve recommendation (A)' })).toBeDisabled()
})

test('whole-store clear invalidates account and deferred receipt', async ({ page }) => {
  await account(page)
  await page.goto('/#/signup')
  await page.evaluate(() => sessionStorage.setItem('dlj-deferred-registration', 'old-receipt'))
  await page.evaluate(() => { localStorage.clear(); window.dispatchEvent(new StorageEvent('storage', { key: null, newValue: null })) })
  await expect(page.locator('#api-key')).toHaveValue('')
  expect(await page.evaluate(() => sessionStorage.getItem('dlj-deferred-registration'))).toBeNull()
})

test('rotating the account cancels a pending report download', async ({ page }) => {
  await account(page)
  await page.route('**/v1/label-health/report', route => route.fulfill({ contentType: 'text/html', body: '<p>Report ready</p>' }))
  let resume!: () => void
  const hold = new Promise<void>(resolve => { resume = resolve })
  await page.route('**/v1/label-health/report/pdf', async route => {
    await hold
    await route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4' })
  })
  const downloads: string[] = []
  page.on('download', download => downloads.push(download.suggestedFilename()))
  await page.goto('/#/health')
  await page.locator('input[type=file]').setInputFiles({ name: 'old.csv', mimeType: 'text/csv', buffer: Buffer.from('a,b\n1,2') })
  const sent = page.waitForRequest(req => req.url().endsWith('/report/pdf'))
  await page.getByRole('button', { name: 'Download PDF' }).click()
  await sent
  const cancelled = page.waitForEvent('requestfailed', req => req.url().endsWith('/report/pdf'))
  try {
    await page.evaluate(() => {
      localStorage.setItem('rgi-api-key', 'key-B')
      window.dispatchEvent(new StorageEvent('storage', { key: 'rgi-api-key', newValue: 'key-B' }))
    })
  } finally { resume() }
  await cancelled
  await expect(page.getByRole('button', { name: 'Download PDF' })).toHaveCount(0)
  expect(downloads).toEqual([])
})

test('report navigation does not retain a File in browser history', async ({ page }) => {
  await account(page)
  let reportRequests = 0
  await page.route('**/v1/label-health/analyze', route => route.fulfill({ json: { metadata: { row_count: 1, verified_count: 0, factor_count: 2 }, warnings: [] } }))
  await page.route('**/v1/label-health/report', route => { reportRequests++; return route.fulfill({ contentType: 'text/html', body: '<h1>Report</h1>' }) })
  await page.goto('/#/upload')
  await page.locator('input[type=file]').setInputFiles({ name: 'old.csv', mimeType: 'text/csv', buffer: Buffer.from('label_id,category,verified_outcome,factor_a,factor_b\nL1,A,true,0.8,0.2') })
  await expect(page.locator('.success')).toContainText('Analysis ready')
  await page.getByRole('button', { name: 'View full report' }).click()
  await expect(page.getByRole('heading', { name: 'Label Health Report' })).toBeVisible()
  expect(await page.evaluate(() => history.state?.usr?.file instanceof File)).toBe(false)
  await page.evaluate(() => localStorage.setItem('rgi-api-key', 'key-B'))
  await page.getByRole('link', { name: 'Settings' }).click()
  const before = reportRequests
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Label Health Report' })).toBeVisible()
  expect(reportRequests).toBe(before)
})
