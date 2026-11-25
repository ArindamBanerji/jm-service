import { expect, test, type Page } from '@playwright/test'

async function account(page: Page) {
  await page.addInitScript(() => {
    if (!localStorage.getItem('rgi-api-key')) localStorage.setItem('rgi-api-key', 'key-A')
    if (!localStorage.getItem('rgi-domain')) localStorage.setItem('rgi-domain', 'alpha')
  })
}

const registration = { api_key: 'registered-key', tenant_id: 'new-tenant', tier: 'trial', message: 'Ready' }

test('cross-tab B then A notifications invalidate an in-flight registration', async ({ page }) => {
  await account(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let started!: () => void
  const requestStarted = new Promise<void>(resolve => { started = resolve })
  await page.route('**/v1/auth/register', async route => {
    started()
    await gate
    await route.fulfill({ status: 202, json: { message: 'Check your email' } })
  })
  await page.goto('/#/signup')
  await page.getByRole('textbox', { name: 'Email' }).fill('cross-tab@example.com')
  await page.getByRole('button', { name: 'Start Free Trial' }).click()
  await requestStarted
  await page.evaluate(() => {
    window.dispatchEvent(new StorageEvent('storage', { key: 'rgi-api-key', oldValue: 'key-A', newValue: 'key-B' }))
    window.dispatchEvent(new StorageEvent('storage', { key: 'rgi-api-key', oldValue: 'key-B', newValue: 'key-A' }))
  })
  const response = page.waitForResponse(result => result.url().endsWith('/v1/auth/register'))
  release()
  await response
  await expect(page.getByRole('button', { name: 'Start Free Trial' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.getItem('rgi-api-key'))).toBe('key-A')
})

test('typed tag draft survives canonical predecessor refetch and successor navigation', async ({ page }) => {
  await account(page)
  const original = { domain_id: 'alpha', label_id: 'item-1', category: 'A', annotator_id: null,
    factors: { confidence: .8 }, recommended_action: 'approve', confidence: .8,
    text: 'Source text', actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: 'rev-1', previous_category: null, status: 'scored',
    content: { content_type: 'text_multilabel', spans: [], tags: ['positive'], image_url: null } }
  const successor = { ...original, label_id: 'item-2', category: 'B', revision_id: 'rev-2', previous_category: 'A' }
  let revised = false
  let predecessorRefetched = false
  await page.route('**/v1/domains/alpha/autonomy', route => route.fulfill({ json: {
    domain_id: 'alpha', overall_tier: 'amber', categories: ['A', 'B'].map(category => ({
      category, tier: 'amber', verified_count: 0, accuracy: null, conservation_gate_pass: true,
      conservation_reason: null, next_tier: 'green', next_tier_requirements: '', recommended_action_policy: 'confirm',
    })),
  } }))
  await page.route('**/v1/domains/alpha/guidelines', route => route.fulfill({ json: { guidelines: '' } }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } }))
  await page.route('**/v1/labels/alpha/items/item-1', route => {
    if (revised) predecessorRefetched = true
    return route.fulfill({ json: revised ? successor : original })
  })
  await page.route('**/v1/labels/alpha/items/item-2', route => route.fulfill({ json: successor }))
  await page.route('**/v1/labels/alpha/items/item-1/relabel', route => {
    revised = true
    return route.fulfill({ json: { label_id: 'item-1', category: 'B', revision_id: 'rev-2', previous_category: 'A' } })
  })
  await page.goto('/#/review/item-1')
  await expect(page.getByRole('heading', { name: 'item-1' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Add tag' }).fill('urgent')
  await page.getByRole('combobox', { name: 'Choose category' }).selectOption('B')
  await page.getByRole('button', { name: 'Relabel' }).click()
  await expect(page).toHaveURL(/#\/review\/item-2$/)
  expect(predecessorRefetched).toBe(true)
  await expect(page.getByRole('heading', { name: 'item-2' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toHaveValue('urgent')
})

test('a persisted signup receipt is removed after a cross-tab credential event', async ({ page }) => {
  await account(page)
  await page.route('**/v1/auth/register', route => route.fulfill({ status: 202, json: { message: 'Check your email' } }))
  await page.route('**/v1/auth/confirm', route => route.fulfill({ status: 201, json: registration }))
  await page.goto('/#/signup')
  await page.getByRole('textbox', { name: 'Email' }).fill('receipt@example.com')
  await page.getByRole('button', { name: 'Start Free Trial' }).click()
  await page.getByRole('textbox', { name: 'Confirmation code' }).fill('a'.repeat(64))
  await page.getByRole('button', { name: 'Confirm email' }).click()
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveValue('registered-key')
  expect(await page.evaluate(() => sessionStorage.getItem('dlj-deferred-registration'))).not.toBeNull()
  await page.goto('/#/upload')
  expect(await page.evaluate(() => sessionStorage.getItem('dlj-deferred-registration'))).not.toBeNull()
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', {
    key: 'rgi-api-key', oldValue: 'registered-key', newValue: 'key-new',
  }))).catch(() => { /* App reloads after account invalidation */ })
  await expect.poll(async () => {
    try { return await page.evaluate(() => sessionStorage.getItem('dlj-deferred-registration')) }
    catch { return 'navigation pending' }
  }).toBeNull()
  await page.goto('/#/signup')
  await expect(page.getByRole('button', { name: 'Start Free Trial' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Your API key' })).toHaveCount(0)
})
