import { expect, test, type Page } from '@playwright/test'

async function workspace(page: Page) {
  await page.addInitScript(() => {
    if (!localStorage.getItem('rgi-api-key')) localStorage.setItem('rgi-api-key', 'key-A')
    if (!localStorage.getItem('rgi-domain')) localStorage.setItem('rgi-domain', 'alpha')
  })
  await page.route('**/v1/domains/alpha/autonomy', route => route.fulfill({ json: {
    domain_id: 'alpha', overall_tier: 'amber', categories: [
      { category: 'A', tier: 'amber', verified_count: 0, accuracy: null, conservation_gate_pass: true,
        conservation_reason: null, next_tier: 'green', next_tier_requirements: '', recommended_action_policy: 'confirm' },
    ],
  } }))
  await page.route('**/v1/domains/alpha/guidelines', route => route.fulfill({ json: { guidelines: '' } }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } }))
}

test('bulk reject transmits reviewer outcome rather than deriving it from action', async ({ page }) => {
  await workspace(page)
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [
    { label_id: 'L1', category: 'A', annotator_id: null, confidence: .8,
      recommended_action: 'approve', text_preview: 'Text' },
  ], headers: { 'X-Total-Count': '1' } }))
  let body: Record<string, unknown> | null = null
  await page.route('**/v1/labels/alpha/bulk-verify', route => {
    body = route.request().postDataJSON() as Record<string, unknown>
    return route.fulfill({ json: { processed: 1, skipped: 0, errors: [] } })
  })
  await page.goto('/#/queue')
  await page.getByRole('checkbox', { name: 'Select L1' }).check()
  await page.getByRole('combobox', { name: 'Bulk known outcome' }).selectOption('correct')
  await page.getByRole('button', { name: 'Reject All' }).click()
  await expect.poll(() => body).not.toBeNull()
  expect(body).toMatchObject({ label_ids: ['L1'], action: 'reject', outcome: true })
})

test('pending registration cannot replace key after A to B to A switch', async ({ page }) => {
  await workspace(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let requested = false
  await page.route('**/v1/auth/register', async route => {
    requested = true
    await gate
    try { await route.fulfill({ status: 201, json: {
      api_key: 'late-key', tenant_id: 'new', tier: 'trial', message: 'Ready',
    } }) } catch { /* aborted on navigation */ }
  })
  await page.goto('/#/signup')
  await page.getByRole('textbox', { name: 'Email' }).fill('late@example.com')
  await page.getByRole('button', { name: 'Start Free Trial' }).click()
  await expect.poll(() => requested).toBe(true)
  await page.goto('/#/upload')
  await page.goto('/#/signup')
  await page.evaluate(() => { localStorage.setItem('rgi-api-key', 'key-B'); window.dispatchEvent(new Event('dlj-key-updated')) })
  await expect.poll(() => page.evaluate(() => localStorage.getItem('rgi-api-key'))).toBe('key-B')
  await page.evaluate(() => { localStorage.setItem('rgi-api-key', 'key-A'); window.dispatchEvent(new Event('dlj-key-updated')) })
  release()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('rgi-api-key'))).toBe('key-A')
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveCount(0)
})

test('old deferred signup receipt is cleared when account changes', async ({ page }) => {
  await workspace(page)
  await page.route('**/v1/auth/register', route => route.fulfill({ status: 201, json: {
    api_key: 'receipt-key', tenant_id: 'new', tier: 'trial', message: 'Ready',
  } }))
  await page.goto('/#/signup')
  await page.getByRole('textbox', { name: 'Email' }).fill('receipt@example.com')
  await page.getByRole('button', { name: 'Start Free Trial' }).click()
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveValue('receipt-key')
  await page.goto('/#/upload')
  await page.evaluate(() => { localStorage.setItem('rgi-api-key', 'key-B'); window.dispatchEvent(new Event('dlj-key-updated')) })
  await page.goto('/#/signup')
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Start Free Trial' })).toBeVisible()
})

test('review editors are locked throughout verification', async ({ page }) => {
  await workspace(page)
  await page.route('**/v1/labels/alpha/items/L1', route => route.fulfill({ json: {
    domain_id: 'alpha', label_id: 'L1', category: 'A', annotator_id: null,
    factors: { confidence: .8 }, recommended_action: 'approve', confidence: .8,
    text: 'Example', actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: 'rev-1', previous_category: null, status: 'scored',
    content: { content_type: 'text_multilabel', spans: [], tags: ['positive'], image_url: null },
  } }))
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let requested = false
  await page.route('**/v1/labels/verify', async route => {
    requested = true
    await gate
    await route.fulfill({ json: { label_id: 'L1', action_taken: 'approve', was_correct: true,
      engine_updated: true, new_accuracy: 1 } })
  })
  await page.goto('/#/review/L1')
  await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct')
  await page.getByRole('button', { name: 'Approve recommendation (A)' }).click()
  await expect.poll(() => requested).toBe(true)
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toBeDisabled()
  await expect(page.getByRole('combobox', { name: 'Choose category' })).toBeDisabled()
  release()
  await expect(page).toHaveURL(/#\/queue$/)
})

test('settings renders null usage counters without crashing', async ({ page }) => {
  await workspace(page)
  await page.route('**/v1/account', route => route.fulfill({ json: {
    tenant_id: 't', tenant_name: 'Account', tier: 'starter', created_at: '2026-11-24T00:00:00Z',
    is_active: true, cancelled_at: null, trial_expires_at: null, trial_expired: false,
    usage: { labels_today: null, labels_this_month: null, daily_cap: null, monthly_cap: null,
      day_key: null, month_key: null },
  } }))
  await page.route('**/v1/account/domains', route => route.fulfill({ json: [] }))
  await page.goto('/#/settings')
  await expect(page.getByRole('heading', { name: 'Key usage' })).toBeVisible()
  await expect(page.getByText('Today (— UTC):')).toContainText('0')
  await expect(page.getByText('This month (— UTC):')).toContainText('0')
})

test('settings treats a malformed string usage object as empty', async ({ page }) => {
  await workspace(page)
  await page.route('**/v1/account', route => route.fulfill({ json: {
    tenant_id: 't', tenant_name: 'Account', tier: 'starter', created_at: '2026-11-24T00:00:00Z',
    is_active: true, cancelled_at: null, trial_expires_at: null, trial_expired: false, usage: 'null',
  } }))
  await page.route('**/v1/account/domains', route => route.fulfill({ json: [] }))
  await page.goto('/#/settings')
  await expect(page.getByRole('heading', { name: 'Key usage' })).toBeVisible()
  await expect(page.getByText('Today (— UTC):')).toContainText('0')
})
