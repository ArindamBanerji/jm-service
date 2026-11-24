import { expect, test, type Page } from '@playwright/test'

test.use({ baseURL: 'http://localhost:8080' })

const categories = ['PERSON', 'ORG'].map(category => ({
  category, tier: 'amber', verified_count: 0, accuracy: null,
  conservation_gate_pass: true, conservation_reason: null, next_tier: 'green',
  next_tier_requirements: '', recommended_action_policy: 'confirm',
}))

async function setup(page: Page, domain = 'alpha') {
  await page.addInitScript(value => {
    localStorage.setItem('rgi-api-key', 'state-test-key')
    localStorage.setItem('rgi-domain', value)
  }, domain)
  await page.route('**/v1/domains/*/autonomy', route => route.fulfill({ json: {
    domain_id: route.request().url().split('/').at(-2), overall_tier: 'amber', categories,
  } }))
  await page.route('**/v1/domains/*/guidelines', route => route.fulfill({ json: { guidelines: '' } }))
}

function detail(domain: string, label: string) {
  return {
    domain_id: domain, label_id: label, category: 'PERSON', annotator_id: 'annotator',
    factors: { model_confidence: 0.7 }, recommended_action: 'approve', confidence: 0.8,
    text: `${label} text`, actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: `revision-${label}`, previous_category: null, status: 'scored', content: null,
  }
}

function row(label: string) {
  return { label_id: label, category: 'PERSON', annotator_id: 'annotator',
    confidence: 0.8, recommended_action: 'approve', text_preview: `${label} text` }
}

test('late label response cannot replace the current review card', async ({ page }) => {
  await setup(page)
  let releaseFirst!: () => void
  const firstGate = new Promise<void>(resolve => { releaseFirst = resolve })
  let finishFirst!: () => void
  const firstDone = new Promise<void>(resolve => { finishFirst = resolve })
  let firstRequested = false
  await page.route('**/v1/labels/alpha/items/one', async route => {
    firstRequested = true
    await firstGate
    try { await route.fulfill({ json: detail('alpha', 'one') }) } catch { /* aborted navigation */ }
    finally { finishFirst() }
  })
  await page.route('**/v1/labels/alpha/items/two', route => route.fulfill({ json: detail('alpha', 'two') }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [row('one'), row('two')], headers: { 'X-Total-Count': '2' } }))
  await page.goto('/#/review/one')
  await expect.poll(() => firstRequested).toBe(true)
  await page.goto('/#/review/two')
  await expect(page.getByRole('heading', { name: 'two' })).toBeVisible()
  releaseFirst()
  await firstDone
  await expect(page.getByRole('heading', { name: 'two' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'one' })).toHaveCount(0)
})

test('queue clears old rows and selection before a new domain loads', async ({ page }) => {
  await setup(page)
  let releaseBeta!: () => void
  const betaGate = new Promise<void>(resolve => { releaseBeta = resolve })
  let betaRequested = false
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [row('old-foo')], headers: { 'X-Total-Count': '1' } }))
  await page.route('**/v1/labels/beta/pending*', async route => {
    betaRequested = true
    await betaGate
    await route.fulfill({ json: [row('new-label')], headers: { 'X-Total-Count': '1' } })
  })
  await page.goto('/#/queue')
  await page.getByRole('searchbox', { name: 'Search labels' }).fill('foo')
  await expect(page.getByRole('status').filter({ hasText: 'results for' })).toContainText('foo')
  await expect(page.getByRole('row').filter({ hasText: 'old-foo' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select old-foo' }).check()
  await page.locator('#domain').fill('beta')
  await expect.poll(() => betaRequested).toBe(true)
  await expect(page.getByRole('row').filter({ hasText: 'old-foo' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Bulk review actions' })).toHaveCount(0)
  releaseBeta()
  await expect(page.getByRole('row').filter({ hasText: 'new-label' })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: 'Search labels' })).toHaveValue('')
})

test('settings loads guidelines for the selected domain before enabling save', async ({ page }) => {
  await setup(page)
  let releaseBeta!: () => void
  const betaGate = new Promise<void>(resolve => { releaseBeta = resolve })
  let betaRequested = false
  await page.route('**/v1/domains/alpha/guidelines', route => route.fulfill({ json: { guidelines: 'Alpha instructions' } }))
  await page.route('**/v1/domains/beta/guidelines', async route => {
    betaRequested = true
    await betaGate
    await route.fulfill({ json: { guidelines: 'Beta instructions' } })
  })
  await page.route('**/v1/account', route => route.fulfill({ status: 401, json: { error: 'test account' } }))
  await page.route('**/v1/account/domains', route => route.fulfill({ json: [] }))
  await page.goto('/#/settings')
  const editor = page.getByRole('textbox', { name: 'Guidelines', exact: true })
  await expect(editor).toHaveValue('Alpha instructions')
  await page.locator('#domain').fill('beta')
  await expect.poll(() => betaRequested).toBe(true)
  await expect(editor).toHaveValue('')
  await expect(page.getByRole('button', { name: 'Save guidelines' })).toBeDisabled()
  releaseBeta()
  await expect(editor).toHaveValue('Beta instructions')
  await expect(page.getByRole('button', { name: 'Save guidelines' })).toBeEnabled()
})

test('editing an entity disables approval until changes are saved', async ({ page }) => {
  await setup(page)
  const item = { ...detail('alpha', 'ner-one'), text: 'John Smith', content: {
    content_type: 'text_ner', spans: [{ start: 0, end: 10, label: 'PERSON', text: 'John Smith' }],
    tags: [], image_url: null,
  } }
  await page.route('**/v1/labels/alpha/items/ner-one', route => route.fulfill({ json: item }))
  await page.route('**/v1/labels/alpha/pending*', route => route.fulfill({ json: [row('ner-one')], headers: { 'X-Total-Count': '1' } }))
  await page.goto('/#/review/ner-one')
  await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct')
  const approve = page.getByRole('button', { name: 'Approve recommendation (A)' })
  await expect(approve).toBeEnabled()
  await page.locator('mark[aria-label^="PERSON: John Smith"]').click()
  await page.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('Unsaved changes')).toBeVisible()
  await expect(approve).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Override (O)' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Escalate (E)' })).toBeDisabled()
})
