import { expect, test, type Page } from '@playwright/test'

type Content = { content_type: 'text_ner' | 'text_multilabel' | 'image_classification'; spans: { start: number; end: number; label: string; text: string }[]; tags: string[]; image_url: string | null }
type Options = { rows?: number; content?: Content | null; verified?: boolean; guidelines?: string; agreement?: { pairs: { annotator_a: string; annotator_b: string; kappa: number | null; overlap_count: number }[]; overall_kappa: number | null; total_overlapping_labels: number } }
const tier = (category: string) => ({ category, tier: 'amber', verified_count: 2, accuracy: .75, conservation_gate_pass: true, conservation_reason: null, next_tier: 'green', next_tier_requirements: 'More reviews', recommended_action_policy: 'confirm' })

async function mock(page: Page, options: Options = {}) {
  const items = Array.from({ length: options.rows ?? 2 }, (_, index) => ({ label_id: `L${String(index + 1).padStart(3, '0')}`, category: 'PERSON', annotator_id: 'ann-1', factors: { model_confidence: .8, item_difficulty: .2 }, confidence: index === 0 ? .8500000001 : .65, recommended_action: 'approve', text_preview: `Source text ${index + 1}` }))
  const posts: { path: string; body: any }[] = []
  const errors: string[] = []
  let guidelines = options.guidelines ?? '## Existing guidance\n- Verify evidence'
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && !/Failed to load resource/.test(message.text())) errors.push(message.text()) })
  await page.addInitScript(() => { localStorage.setItem('rgi-api-key', 'component-key'); localStorage.setItem('rgi-domain', 'alpha'); if (!localStorage.getItem('dlj-theme')) localStorage.setItem('dlj-theme', 'light') })
  await page.route('**/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    const body = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : null
    if (request.method() !== 'GET') posts.push({ path, body })
    const send = (json: unknown, headers?: Record<string, string>) => route.fulfill({ json, headers })
    if (path === '/v1/labels/alpha/pending') { const offset = Number(url.searchParams.get('offset') ?? 0), limit = Number(url.searchParams.get('limit') ?? 50); return send(items.slice(offset, offset + limit), { 'X-Total-Count': String(items.length) }) }
    if (path === '/v1/domains/alpha/autonomy') return send({ domain_id: 'alpha', overall_tier: 'amber', categories: ['PERSON', 'ORG', 'URGENT'].map(tier) })
    if (path === '/v1/domains/alpha/guidelines') { if (request.method() === 'PUT') guidelines = body.guidelines; return send({ guidelines }) }
    if (path === '/v1/labels/alpha/items/L001') return send({ ...items[0], domain_id: 'alpha', text: 'Source text 1', actual_action: options.verified ? 'approve' : null, verified_outcome: options.verified ? true : null, verified_at: options.verified ? '2026-11-24T00:00:00Z' : null, revision_id: 'revision-1', previous_category: null, status: 'scored', content: options.content ?? null })
    if (path === '/v1/labels/alpha/items/L001/relabel') return send({ label_id: 'L001', category: body.category, revision_id: 'revision-2', previous_category: 'PERSON' })
    if (path === '/v1/labels/alpha/bulk-verify') { for (const id of body.label_ids) { const index = items.findIndex(value => value.label_id === id); if (index >= 0) items.splice(index, 1) } return send({ processed: body.label_ids.length, skipped: 0, errors: [] }) }
    if (path === '/v1/account') return send({ tenant_id: 't1', tenant_name: 'Test tenant', tier: 'trial', created_at: '2026-01-01T00:00:00Z', is_active: true, cancelled_at: null, trial_expires_at: null, trial_expired: false, usage: { labels_today: 0, labels_this_month: 0, daily_cap: 50, monthly_cap: null, day_key: '2026-11-24', month_key: '2026-11' } })
    if (path === '/v1/account/domains') return send([{ id: 'alpha', public_domain_id: 'alpha', needs_name: false }])
    if (path === '/v1/dashboard/alpha/overview') return send({ domain_id: 'alpha', overall_accuracy: .75, total_verified: 4, total_labels: 6, categories: [tier('PERSON')], inversion: null, compounding_curve: [], generated_at: '2026-11-24T00:00:00Z' })
    if (path === '/v1/dashboard/alpha/corrections') return send({ domain_id: 'alpha', total_corrections: 0, correction_rate: null, patterns: [], top_pattern: null })
    if (path === '/v1/dashboard/alpha/compounding') return send({ domain_id: 'alpha', category: null, points: [], baseline_accuracy: null, current_accuracy: null, improvement: null })
    if (path === '/v1/dashboard/alpha/iaa') return send(options.agreement ?? { pairs: [], overall_kappa: null, total_overlapping_labels: 0 })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  return { items, posts, errors, getGuidelines: () => guidelines }
}

const tags = (): Content => ({ content_type: 'text_multilabel', spans: [], tags: ['positive'], image_url: null })
const image = (url: string | null): Content => ({ content_type: 'image_classification', spans: [], tags: [], image_url: url })

test('TagSelector shows existing tags and autocomplete suggestions', async ({ page }) => {
  const state = await mock(page, { content: tags() }); await page.goto('/#/review/L001')
  const region = page.getByRole('region', { name: 'Multi-label tags' })
  await expect(region).toContainText('positive')
  await page.getByRole('combobox', { name: 'Add tag' }).fill('urg')
  await expect(region.getByRole('option', { name: 'URGENT' })).toBeVisible()
  expect(state.errors).toEqual([])
})

test('TagSelector adds and removes multiple tags', async ({ page }) => {
  const state = await mock(page, { content: tags() }); await page.goto('/#/review/L001')
  const input = page.getByRole('combobox', { name: 'Add tag' })
  await input.fill('ORG'); await input.press('Enter')
  await expect(page.getByRole('button', { name: 'Remove ORG' })).toBeVisible()
  await input.fill('custom'); await input.press('Enter')
  await expect(page.getByRole('region', { name: 'Multi-label tags' })).toContainText('custom')
  await page.getByRole('button', { name: 'Remove ORG' }).click()
  await expect(page.getByRole('button', { name: 'Remove ORG' })).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('TagSelector on a verified label is read only', async ({ page }) => {
  const state = await mock(page, { content: tags(), verified: true }); await page.goto('/#/review/L001')
  await expect(page.getByRole('region', { name: 'Multi-label tags' })).toContainText('positive')
  await expect(page.getByRole('combobox', { name: 'Add tag' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Remove positive' })).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('ImageViewer renders a provided image and category', async ({ page }) => {
  const state = await mock(page, { content: image('https://images.example.test/source.png') })
  await page.route('https://images.example.test/source.png', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="blue"/></svg>' }))
  await page.goto('/#/review/L001')
  await expect(page.getByRole('region', { name: 'Image classification' }).getByRole('img', { name: 'Source image for classification' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Image classification' })).toContainText('Category: PERSON')
  expect(state.errors).toEqual([])
})

test('ImageViewer reports a broken image without edit controls', async ({ page }) => {
  const state = await mock(page, { content: image('https://images.example.test/missing.png') })
  await page.route('https://images.example.test/missing.png', route => route.fulfill({ status: 404, body: '' }))
  await page.goto('/#/review/L001')
  await expect(page.getByRole('alert').filter({ hasText: 'Image not available' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Image classification' }).getByRole('button')).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('missing image URL leaves the image viewer unmounted', async ({ page }) => {
  const state = await mock(page, { content: image(null) }); await page.goto('/#/review/L001')
  await expect(page.getByRole('region', { name: 'Image classification' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Category' })).toBeVisible()
  expect(state.errors).toEqual([])
})

test('CategorySelector shows the current category and schema options', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/review/L001')
  const select = page.getByRole('combobox', { name: 'Choose category' })
  await expect(select).toHaveValue('PERSON')
  await expect(select.locator('option')).toContainText(['Select a category…', 'PERSON', 'ORG', 'URGENT', 'New category…'])
  expect(state.errors).toEqual([])
})

test('CategorySelector sends a revision token for changed category', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/review/L001')
  await page.getByRole('combobox', { name: 'Choose category' }).selectOption('ORG')
  const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/alpha/items/L001/relabel'))
  await page.getByRole('button', { name: 'Relabel' }).click(); await response
  expect(state.posts.at(-1)?.body).toEqual({ category: 'ORG', idempotency_token: 'revision-1' })
  await expect(page.getByText('Category saved.')).toBeVisible()
  expect(state.errors).toEqual([])
})

test('CategorySelector disables Relabel for the unchanged category', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/review/L001')
  await expect(page.getByRole('combobox', { name: 'Choose category' })).toHaveValue('PERSON')
  await expect(page.getByRole('button', { name: 'Relabel' })).toBeDisabled()
  expect(state.posts.filter(post => post.path.endsWith('/relabel'))).toHaveLength(0)
  expect(state.errors).toEqual([])
})

test('GuidelinesPanel renders markdown loaded from the API', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/review/L001')
  await page.getByRole('button', { name: 'Guidelines' }).click()
  const region = page.getByRole('region', { name: 'Annotation guidelines' })
  await expect(region.getByRole('heading', { name: 'Existing guidance' })).toBeVisible()
  await expect(region).toContainText('Verify evidence')
  expect(state.errors).toEqual([])
})

test('Settings guidelines editor saves text through PUT', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/settings')
  const editor = page.getByRole('textbox', { name: 'Guidelines', exact: true })
  await expect(editor).toHaveValue('## Existing guidance\n- Verify evidence')
  await editor.fill('New policy')
  const response = page.waitForResponse(r => r.url().endsWith('/v1/domains/alpha/guidelines') && r.request().method() === 'PUT')
  await page.getByRole('button', { name: 'Save guidelines' }).click(); await response
  expect(state.posts.at(-1)?.body).toEqual({ guidelines: 'New policy' })
  await expect(page.getByText('Guidelines saved.')).toBeVisible()
  expect(state.errors).toEqual([])
})

test('GuidelinesPanel explains when no guidance is configured', async ({ page }) => {
  const state = await mock(page, { guidelines: '' }); await page.goto('/#/review/L001')
  await page.getByRole('button', { name: 'Guidelines' }).click()
  await expect(page.getByRole('region', { name: 'Annotation guidelines' })).toContainText('No guidelines configured')
  expect(state.errors).toEqual([])
})

test('IAAPanel renders Cohen kappa and pair overlap', async ({ page }) => {
  const state = await mock(page, { agreement: { overall_kappa: .72, total_overlapping_labels: 12, pairs: [{ annotator_a: 'ann-1', annotator_b: 'ann-2', kappa: .72, overlap_count: 12 }] } })
  await page.goto('/#/dashboard')
  await expect(page.getByRole('heading', { name: 'Inter-annotator agreement' })).toBeVisible()
  await expect(page.getByText('Overall Cohen’s κ:')).toContainText('0.72')
  await expect(page.getByRole('row').filter({ hasText: 'ann-1' })).toContainText('12')
  expect(state.errors).toEqual([])
})

test('IAAPanel explains an empty agreement result', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/dashboard')
  await expect(page.getByRole('heading', { name: 'Inter-annotator agreement' })).toBeVisible()
  await expect(page.getByText('Need 2+ annotators with overlapping labels to calculate agreement')).toBeVisible()
  expect(state.errors).toEqual([])
})

test('IAAPanel shows a dash for undefined pair kappa', async ({ page }) => {
  const state = await mock(page, { agreement: { overall_kappa: null, total_overlapping_labels: 1, pairs: [{ annotator_a: 'ann-1', annotator_b: 'ann-2', kappa: null, overlap_count: 1 }] } })
  await page.goto('/#/dashboard')
  await expect(page.getByText('Overall Cohen’s κ:')).toContainText('—')
  await expect(page.getByRole('row').filter({ hasText: 'ann-1' })).toContainText('—')
  expect(state.errors).toEqual([])
})

test('keyboard help lists actual bindings and closes with Escape', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/queue')
  await page.getByRole('heading', { name: /Scored Queue/ }).click(); await page.keyboard.press('?')
  const modal = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(modal).toBeVisible()
  for (const key of ['g u', 'g q', 'g d', 'g s', 'g h', 'j / k', 'Enter', 'Ctrl+A', 'A', 'O', 'E']) await expect(modal.locator('kbd').filter({ hasText: key }).first()).toBeVisible()
  await page.keyboard.press('Escape'); await expect(modal).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('keyboard shortcut g q navigates from Settings to Queue', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/settings')
  await page.getByRole('heading', { name: 'Settings' }).click(); await page.keyboard.press('g'); await page.keyboard.press('q')
  await expect(page).toHaveURL(/#\/queue$/); await expect(page.locator('tbody tr')).toHaveCount(2)
  expect(state.errors).toEqual([])
})

test('keyboard help closes using the Close button', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/upload')
  await page.getByRole('heading', { name: 'Start with your labels.' }).click(); await page.keyboard.press('?')
  const modal = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(modal).toBeVisible(); await modal.getByRole('button', { name: 'Close' }).click()
  await expect(modal).toHaveCount(0); expect(state.errors).toEqual([])
})

test('dark toggle changes page and card styling', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/queue')
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Toggle dark mode' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  const background = await page.locator('.card').first().evaluate(element => getComputedStyle(element).backgroundColor)
  expect(background).toBe('rgb(29, 41, 57)')
  expect(state.errors).toEqual([])
})

test('dark toggle persists in localStorage after reload', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/upload')
  await page.getByRole('button', { name: 'Toggle dark mode' }).click(); await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  expect(await page.evaluate(() => localStorage.getItem('dlj-theme'))).toBe('dark')
  expect(state.errors).toEqual([])
})

test('dark toggle restores light card styling', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/queue')
  const toggle = page.getByRole('button', { name: 'Toggle dark mode' })
  await toggle.click(); await expect(page.locator('html')).toHaveClass(/dark/)
  await toggle.click(); await expect(page.locator('html')).not.toHaveClass(/dark/)
  expect(await page.locator('.card').first().evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(255, 255, 255)')
  expect(state.errors).toEqual([])
})

test('bulk action bar tracks individual selection and clear', async ({ page }) => {
  const state = await mock(page, { rows: 3 }); await page.goto('/#/queue')
  const bar = page.getByRole('region', { name: 'Bulk review actions' })
  await expect(bar).toHaveCount(0)
  await page.getByRole('checkbox', { name: 'Select L001' }).check(); await expect(bar).toContainText('1 selected')
  await page.getByRole('checkbox', { name: 'Select L002' }).check(); await expect(bar).toContainText('2 selected')
  await bar.getByRole('button', { name: 'Clear Selection' }).click(); await expect(bar).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('bulk page selection and approval send exact IDs', async ({ page }) => {
  const state = await mock(page, { rows: 3 }); await page.goto('/#/queue')
  await page.getByRole('checkbox', { name: 'Select all on this page' }).check()
  await expect(page.getByRole('region', { name: 'Bulk review actions' })).toContainText('3 selected')
  const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/alpha/bulk-verify'))
  await page.getByRole('button', { name: 'Approve All' }).click(); await response
  expect(state.posts.at(-1)?.body).toEqual({ label_ids: ['L001', 'L002', 'L003'], action: 'approve' })
  await expect(page.getByRole('region', { name: 'Bulk review actions' })).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('bulk select-all checkbox also deselects the page', async ({ page }) => {
  const state = await mock(page, { rows: 3 }); await page.goto('/#/queue')
  const all = page.getByRole('checkbox', { name: 'Select all on this page' })
  await all.check(); await expect(page.getByRole('region', { name: 'Bulk review actions' })).toContainText('3 selected')
  await all.uncheck(); await expect(page.getByRole('region', { name: 'Bulk review actions' })).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('queue confidence displays a rounded numeric percentage', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/queue')
  await expect(page.getByRole('row').filter({ hasText: 'L001' }).locator('.confidence strong')).toHaveText('85%')
  await expect(page.getByRole('row').filter({ hasText: 'L002' }).locator('.confidence strong')).toHaveText('65%')
  expect(state.errors).toEqual([])
})

test('queue confidence track has a bounded fill width', async ({ page }) => {
  const state = await mock(page); await page.goto('/#/queue')
  await expect(page.getByRole('row').filter({ hasText: 'L001' }).locator('.confidence .fill')).toHaveAttribute('style', /width: 85/)
  await expect(page.getByRole('row').filter({ hasText: 'L002' }).locator('.confidence .fill')).toHaveAttribute('style', /width: 65/)
  expect(state.errors).toEqual([])
})

test('queue confidence rounds a very small score to zero percent', async ({ page }) => {
  const state = await mock(page); state.items[0].confidence = .001; await page.goto('/#/queue')
  await expect(page.getByRole('row').filter({ hasText: 'L001' }).locator('.confidence strong')).toHaveText('0%')
  await expect(page.getByRole('row').filter({ hasText: 'L001' }).locator('.confidence .fill')).toHaveAttribute('style', /width: 0.1%/)
  expect(state.errors).toEqual([])
})

test('pagination buttons are disabled on a single page', async ({ page }) => {
  const state = await mock(page, { rows: 2 }); await page.goto('/#/queue')
  await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled()
  await expect(page.locator('.queue-pages')).toContainText('Page 1 of 1')
  expect(state.errors).toEqual([])
})

test('pagination loads a second page and disables Next at the end', async ({ page }) => {
  const state = await mock(page, { rows: 55 }); await page.goto('/#/queue')
  await expect(page.locator('tbody tr')).toHaveCount(50)
  await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled()
  const response = page.waitForResponse(r => new URL(r.url()).searchParams.get('offset') === '50')
  await page.getByRole('button', { name: 'Next' }).click(); await response
  await expect(page.locator('tbody tr')).toHaveCount(5)
  await expect(page.locator('.queue-pages')).toContainText('Page 2 of 2')
  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Previous' })).toBeEnabled()
  expect(state.errors).toEqual([])
})

test('pagination Previous returns to the first page', async ({ page }) => {
  const state = await mock(page, { rows: 55 }); await page.goto('/#/queue')
  await expect(page.locator('tbody tr')).toHaveCount(50)
  await page.getByRole('button', { name: 'Next' }).click(); await expect(page.locator('tbody tr')).toHaveCount(5)
  await page.getByRole('button', { name: 'Previous' }).click(); await expect(page.locator('tbody tr')).toHaveCount(50)
  await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled()
  expect(state.errors).toEqual([])
})
