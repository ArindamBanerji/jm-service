import { expect, test, type Page } from '@playwright/test'

test.use({ baseURL: 'http://localhost:8080' })

const categories = ['PERSON', 'ORG'].map(category => ({
  category, tier: 'amber', verified_count: 0, accuracy: null,
  conservation_gate_pass: true, conservation_reason: null, next_tier: 'green',
  next_tier_requirements: '', recommended_action_policy: 'confirm',
}))

async function setup(page: Page, domain = 'alpha') {
  await page.addInitScript(value => {
    localStorage.setItem('rgi-api-key', 'original-key')
    localStorage.setItem('rgi-domain', value)
  }, domain)
  await page.route('**/v1/domains/*/autonomy', route => route.fulfill({ json: {
    domain_id: domain, overall_tier: 'amber', categories,
  } }))
  await page.route('**/v1/domains/*/guidelines', route => route.fulfill({ json: { guidelines: '' } }))
}

const pendingRow = { label_id: 'bulk-one', category: 'PERSON', annotator_id: 'annotator',
  confidence: 0.8, recommended_action: 'approve', text_preview: 'Example text' }

test('bulk approval sends an explicit verified outcome', async ({ page }) => {
  await setup(page)
  let requestBody: Record<string, unknown> | null = null
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [pendingRow], headers: { 'X-Total-Count': '1' } }))
  await page.route('**/v1/labels/alpha/bulk-verify', route => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>
    return route.fulfill({ json: { processed: 1, skipped: 0, errors: [] } })
  })
  await page.goto('/#/queue')
  await page.getByRole('checkbox', { name: 'Select bulk-one' }).check()
  await page.getByRole('button', { name: 'Approve All' }).click()
  await expect.poll(() => requestBody).not.toBeNull()
  expect(requestBody).toMatchObject({ label_ids: ['bulk-one'], action: 'approve', verified_outcome: true })
})

test('late signup response keeps the credential chosen after navigation', async ({ page }) => {
  await setup(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let requested = false
  let finished!: () => void
  const done = new Promise<void>(resolve => { finished = resolve })
  await page.route('**/v1/auth/register', async route => {
    requested = true
    await gate
    try { await route.fulfill({ json: { api_key: 'late-signup-key', tenant_id: 'new-tenant', tier: 'trial', message: 'Ready' } }) }
    finally { finished() }
  })
  await page.goto('/#/signup')
  await page.getByRole('textbox', { name: 'Email' }).fill('late@example.com')
  await page.getByRole('button', { name: 'Start Free Trial' }).click()
  await expect.poll(() => requested).toBe(true)
  await page.goto('/#/upload')
  await page.evaluate(() => localStorage.setItem('rgi-api-key', 'chosen-key'))
  release()
  await done
  await expect.poll(() => page.evaluate(() => localStorage.getItem('rgi-api-key'))).toBe('chosen-key')
  await page.goto('/#/signup')
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveValue('late-signup-key')
  await expect(page.getByText('This key is not active on this browser.')).toBeVisible()
})

test('credential abort clears the selected CSV and upload form', async ({ page }) => {
  await setup(page)
  const csv = 'label_id,category,factor_model_confidence,factor_item_difficulty\nL1,PERSON,0.8,0.2\nL2,PERSON,0.7,0.3\n'
  await page.route('**/v1/label-health/analyze', route => route.fulfill({ json: {
    report_version: '1', metadata: { row_count: 2, category_count: 1, factor_count: 2,
      verified_count: 0, analysis_time_ms: 1 }, warnings: [],
  } }))
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let batchRequested = false
  await page.route('**/v1/labels/ingest/batch', async route => {
    batchRequested = true
    await gate
    try { await route.fulfill({ json: { results: [], batch_size: 2 } }) } catch { /* aborted request */ }
  })
  await page.goto('/#/upload')
  await page.locator('input[type="file"]').setInputFiles({ name: 'old.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await expect(page.getByText('Analysis ready', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Start scoring these labels' }).click()
  await expect.poll(() => batchRequested).toBe(true)
  await page.evaluate(() => {
    localStorage.setItem('rgi-api-key', 'new-key')
    window.dispatchEvent(new Event('dlj-key-updated'))
  })
  release()
  await expect(page.getByText(/Import stopped: account changed during upload/)).toBeVisible()
  await expect(page.getByText('old.csv')).toHaveCount(0)
  await expect(page.getByText('Analysis ready', { exact: false })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Start scoring these labels' })).toHaveCount(0)
  expect(await page.locator('input[type="file"]').evaluate((input: HTMLInputElement) => input.files?.length)).toBe(0)
})

test('tag input survives a locked category save', async ({ page }) => {
  await setup(page)
  const item = (label: string, category: string, revision: string) => ({
    domain_id: 'alpha', label_id: label, category, annotator_id: 'annotator',
    factors: { model_confidence: 0.8 }, recommended_action: 'approve', confidence: 0.8,
    text: 'Example text', actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: revision, previous_category: null, status: 'scored',
    content: { content_type: 'text_multilabel', spans: [], tags: ['PERSON'], image_url: null },
  })
  await page.route('**/v1/labels/alpha/items/tag-one', route => route.fulfill({ json: item('tag-one', 'PERSON', 'revision-1') }))
  await page.route('**/v1/labels/alpha/items/tag-two', route => route.fulfill({ json: item('tag-two', 'ORG', 'revision-2') }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } }))
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let saveRequested = false
  await page.route('**/v1/labels/alpha/items/tag-one/relabel', async route => {
    saveRequested = true
    await gate
    await route.fulfill({ json: { label_id: 'tag-two', category: 'ORG', revision_id: 'revision-2', previous_category: 'PERSON' } })
  })
  await page.goto('/#/review/tag-one')
  const tagInput = page.getByRole('combobox', { name: 'Add tag' })
  await tagInput.fill('draft-tag')
  await page.getByRole('combobox', { name: 'Choose category' }).selectOption('ORG')
  await page.getByRole('button', { name: 'Relabel' }).click()
  await expect.poll(() => saveRequested).toBe(true)
  await expect(tagInput).toBeDisabled()
  await expect(tagInput).toHaveValue('draft-tag')
  release()
  await expect(page).toHaveURL(/#\/review\/tag-two$/)
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toHaveValue('draft-tag')
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toBeEnabled()
})

test('settings renders account usage defaults when usage is absent', async ({ page }) => {
  await setup(page)
  await page.route('**/v1/account', route => route.fulfill({ json: {
    tenant_id: 'tenant-one', tenant_name: 'New account', tier: 'starter', created_at: '2026-11-24T00:00:00Z',
    is_active: true, cancelled_at: null, trial_expires_at: null, trial_expired: false,
  } }))
  await page.route('**/v1/account/domains', route => route.fulfill({ json: [] }))
  await page.goto('/#/settings')
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Key usage' })).toBeVisible()
  await expect(page.getByText('New account')).toBeVisible()
  await expect(page.getByText('Today (— UTC):')).toBeVisible()
})
