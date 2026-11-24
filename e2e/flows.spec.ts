import { expect, test, type Page } from '@playwright/test'

type Row = { label_id: string; category: string; annotator_id: string | null; factors: Record<string, number>; confidence: number; recommended_action: string; text_preview: string | null }
type Detail = Row & { domain_id: string; text: string | null; actual_action: string | null; verified_outcome: boolean | null; verified_at: string | null; revision_id: string; previous_category: string | null; status: 'scored'; content: null | { content_type: string; spans: { start: number; end: number; label: string; text: string }[]; tags: string[]; image_url: string | null } }
const row = (label_id: string, category = 'PERSON', confidence = .85): Row => ({ label_id, category, annotator_id: 'ann-1', factors: { model_confidence: .8, item_difficulty: .2 }, confidence, recommended_action: 'approve', text_preview: `${label_id} source text` })
const detail = (domain_id: string, item: Row): Detail => ({ ...item, domain_id, text: item.text_preview, actual_action: null, verified_outcome: null, verified_at: null, revision_id: `rev-${item.label_id}`, previous_category: null, status: 'scored', content: null })
const tier = (category: string) => ({ category, tier: 'amber', verified_count: 0, accuracy: null, conservation_gate_pass: true, conservation_reason: null, next_tier: 'green', next_tier_requirements: '', recommended_action_policy: 'confirm' })

async function workspace(page: Page, initial: Record<string, Row[]> = { alpha: [row('A1')] }) {
  const rows: Record<string, Row[]> = Object.fromEntries(Object.entries(initial).map(([key, value]) => [key, [...value]]))
  const details = new Map<string, Detail>()
  for (const [domain, items] of Object.entries(rows)) for (const item of items) details.set(`${domain}/${item.label_id}`, detail(domain, item))
  const guidelines: Record<string, string> = {}
  const posts: { path: string; body: any }[] = []
  const consoleErrors: string[] = []
  page.on('pageerror', error => consoleErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && !/Failed to load resource/.test(message.text())) consoleErrors.push(message.text()) })
  await page.addInitScript(() => { localStorage.setItem('rgi-api-key', 'flow-key'); localStorage.setItem('rgi-domain', 'alpha'); if (!localStorage.getItem('dlj-theme')) localStorage.setItem('dlj-theme', 'light') })
  await page.route('**/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    const body = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : null
    if (method !== 'GET') posts.push({ path, body })
    const send = (json: unknown, headers?: Record<string, string>) => route.fulfill({ json, headers })
    const pending = path.match(/^\/v1\/labels\/([^/]+)\/pending$/)
    if (pending) {
      const domain = decodeURIComponent(pending[1]); let items = rows[domain] ?? []
      const search = url.searchParams.get('search')?.toLowerCase()
      if (search) items = items.filter(item => [item.label_id, item.category, item.annotator_id, item.text_preview].some(value => value?.toLowerCase().includes(search)))
      const category = url.searchParams.get('category'); if (category) items = items.filter(item => item.category === category)
      const total = items.length, offset = Number(url.searchParams.get('offset') ?? 0), limit = Number(url.searchParams.get('limit') ?? 50)
      return send(items.slice(offset, offset + limit), { 'X-Total-Count': String(total) })
    }
    const item = path.match(/^\/v1\/labels\/([^/]+)\/items\/([^/]+)$/)
    if (item) return send(details.get(`${decodeURIComponent(item[1])}/${decodeURIComponent(item[2])}`) ?? null)
    const autonomy = path.match(/^\/v1\/domains\/([^/]+)\/autonomy$/)
    if (autonomy) return send({ domain_id: autonomy[1], overall_tier: 'amber', categories: ['PERSON', 'ORG', 'URGENT'].map(tier) })
    const guide = path.match(/^\/v1\/domains\/([^/]+)\/guidelines$/)
    if (guide) { if (method === 'PUT') guidelines[guide[1]] = body.guidelines; return send({ guidelines: guidelines[guide[1]] ?? '' }) }
    if (path === '/v1/account') return send({ tenant_id: 'tenant-1', tenant_name: 'Flow test tenant', tier: 'trial', created_at: '2026-01-01T00:00:00Z', is_active: true, cancelled_at: null, trial_expires_at: '2026-12-31T00:00:00Z', trial_expired: false, usage: { labels_today: 1, labels_this_month: 1, daily_cap: 50, monthly_cap: null, day_key: '2026-11-24', month_key: '2026-11' } })
    if (path === '/v1/account/domains') return send(Object.keys(rows).map(id => ({ id, public_domain_id: id, needs_name: false })))
    if (path === '/v1/label-health/analyze') return send({ metadata: { row_count: 1, verified_count: 0, factor_count: 2 }, warnings: [] })
    if (path === '/v1/labels/ingest/batch') { const domain = body.domain_id as string; rows[domain] ??= []; for (const entry of body.items) { const itemRow = { ...row(entry.label_id, entry.category), factors: entry.factors, text_preview: entry.text }; rows[domain].push(itemRow); details.set(`${domain}/${entry.label_id}`, detail(domain, itemRow)) } return send({ batch_size: body.items.length, results: body.items.map((entry: Row) => ({ label_id: entry.label_id, category: entry.category, recommended_action: 'approve', confidence: .85 })) }) }
    if (path === '/v1/labels/verify') { const key = `${body.domain_id}/${body.label_id}`, current = details.get(key); if (current) details.set(key, { ...current, actual_action: body.actual_action, verified_outcome: body.verified_outcome, verified_at: '2026-11-24T12:00:00Z' }); rows[body.domain_id] = (rows[body.domain_id] ?? []).filter(value => value.label_id !== body.label_id); return send({ label_id: body.label_id, action_taken: body.actual_action, was_correct: body.verified_outcome, engine_updated: true, new_accuracy: 1 }) }
    const bulk = path.match(/^\/v1\/labels\/([^/]+)\/bulk-verify$/)
    if (bulk) { rows[bulk[1]] = (rows[bulk[1]] ?? []).filter(value => !body.label_ids.includes(value.label_id)); return send({ processed: body.label_ids.length, skipped: 0, errors: [] }) }
    const relabel = path.match(/^\/v1\/labels\/([^/]+)\/items\/([^/]+)\/relabel$/)
    if (relabel) { const key = `${relabel[1]}/${relabel[2]}`, current = details.get(key)!; details.set(key, { ...current, category: body.category, revision_id: 'rev-2', previous_category: current.category, content: current.content ? { ...current.content, spans: body.spans ?? current.content.spans, tags: body.tags ?? current.content.tags } : null }); return send({ label_id: relabel[2], category: body.category, revision_id: 'rev-2', previous_category: current.category }) }
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${method} ${path}` } })
  })
  return { rows, details, guidelines, posts, consoleErrors }
}

const queue = (page: Page) => page.getByRole('link', { name: 'Scored Queue' })
const reviewRow = (page: Page, id: string) => page.getByRole('row').filter({ hasText: id }).getByRole('link', { name: 'Review →' })
const noErrors = (errors: string[]) => expect(errors).toEqual([])

test('upload → queue → review → verify', async ({ page }) => {
  const state = await workspace(page, { alpha: [] })
  await test.step('upload CSV and inspect analysis', async () => { await page.goto('/#/upload'); await expect(page.getByRole('heading', { name: 'Start with your labels.' })).toBeVisible(); await page.evaluate(() => { const csv = 'label_id,category,factor_model_confidence,factor_item_difficulty,text\nU1,PERSON,0.8,0.2,Uploaded source'; const transfer = new DataTransfer(); transfer.items.add(new File([csv], 'labels.csv', { type: 'text/csv' })); const input = document.querySelector<HTMLInputElement>('input[type=file]')!; input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true })) }); await expect(page.locator('.success')).toContainText('Analysis ready') })
  await test.step('score and find uploaded label in queue', async () => { const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/ingest/batch')); await page.getByRole('button', { name: 'Start scoring these labels' }).click(); await response; await expect(page).toHaveURL(/#\/queue$/); await expect(page.getByRole('row').filter({ hasText: 'U1' })).toBeVisible(); expect(state.posts.find(post => post.path === '/v1/labels/ingest/batch')?.body.items[0].text).toBe('Uploaded source') })
  await test.step('open review and verify recommendation', async () => { await reviewRow(page, 'U1').click(); await expect(page.getByRole('heading', { name: 'U1' })).toBeVisible(); await expect(page.getByRole('region', { name: 'Source text' })).toContainText('Uploaded source'); await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct'); const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/verify')); await page.getByRole('button', { name: 'Approve recommendation (A)' }).click(); await response; expect(state.posts.at(-1)?.body).toMatchObject({ domain_id: 'alpha', label_id: 'U1', actual_action: 'approve', verified_outcome: true }); await expect(page).toHaveURL(/#\/queue$/); await expect(page.getByRole('row').filter({ hasText: 'U1' })).toHaveCount(0); noErrors(state.consoleErrors) })
})

test('bulk review selects three labels and clears the action bar', async ({ page }) => {
  const state = await workspace(page, { alpha: Array.from({ length: 12 }, (_, n) => row(`A${n + 1}`)) })
  await test.step('load twelve pending labels', async () => { const response = page.waitForResponse(r => r.url().includes('/v1/labels/alpha/pending')); await page.goto('/#/queue'); await response; await expect(page.locator('tbody tr')).toHaveCount(12) })
  await test.step('select exactly three rows', async () => { for (const id of ['A1', 'A2', 'A3']) await page.getByRole('checkbox', { name: `Select ${id}`, exact: true }).check(); await expect(page.getByRole('region', { name: 'Bulk review actions' })).toContainText('3 selected') })
  await test.step('approve and reload pending rows', async () => { await page.getByRole('combobox', { name: 'Bulk known outcome' }).selectOption('correct'); const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/alpha/bulk-verify')); await page.getByRole('button', { name: 'Approve All' }).click(); await response; expect(state.posts.at(-1)?.body).toEqual({ label_ids: ['A1', 'A2', 'A3'], action: 'approve', outcome: true }); await expect(page.locator('tbody tr')).toHaveCount(9); await expect(page.getByRole('region', { name: 'Bulk review actions' })).toHaveCount(0); await expect(page.getByRole('status').filter({ hasText: 'Approved 3' })).toBeVisible(); noErrors(state.consoleErrors) })
})

test('search → filter → review → back to queue', async ({ page }) => {
  const state = await workspace(page, { alpha: [row('needle-1'), row('other-2')] })
  await test.step('search the pending API', async () => { await page.goto('/#/queue'); const response = page.waitForResponse(r => new URL(r.url()).searchParams.get('search') === 'needle'); await page.getByRole('searchbox', { name: 'Search labels' }).fill('needle'); await response; await expect(page.locator('tbody tr')).toHaveCount(1); await expect(page.getByRole('row').filter({ hasText: 'needle-1' })).toBeVisible() })
  await test.step('review the filtered result', async () => { await reviewRow(page, 'needle-1').click(); await expect(page.getByRole('heading', { name: 'needle-1' })).toBeVisible(); await expect(page.getByRole('region', { name: 'Source text' })).toContainText('needle-1 source') })
  await test.step('return and restore the filter', async () => { await queue(page).click(); await expect(page).toHaveURL(/#\/queue$/); await page.getByRole('searchbox', { name: 'Search labels' }).fill('needle'); await expect(page.locator('tbody tr')).toHaveCount(1); await expect(page.getByRole('searchbox', { name: 'Search labels' })).toHaveValue('needle'); noErrors(state.consoleErrors) })
})

test('domain switch keeps queues and selection isolated', async ({ page }) => {
  const state = await workspace(page, { alpha: Array.from({ length: 5 }, (_, n) => row(`alpha-${n}`)), beta: Array.from({ length: 3 }, (_, n) => row(`beta-${n}`)) })
  await test.step('select two alpha labels', async () => { await page.goto('/#/queue'); await expect(page.locator('tbody tr')).toHaveCount(5); await page.getByRole('checkbox', { name: 'Select alpha-0' }).check(); await page.getByRole('checkbox', { name: 'Select alpha-1' }).check(); await expect(page.getByRole('region', { name: 'Bulk review actions' })).toContainText('2 selected') })
  await test.step('switch to beta with no alpha selection', async () => { const response = page.waitForResponse(r => r.url().includes('/v1/labels/beta/pending')); await page.locator('#domain').fill('beta'); await response; await expect(page.locator('tbody tr')).toHaveCount(3); await expect(page.getByRole('row').filter({ hasText: 'alpha-' })).toHaveCount(0); await expect(page.getByRole('region', { name: 'Bulk review actions' })).toHaveCount(0) })
  await test.step('switch back to alpha without beta rows', async () => { const response = page.waitForResponse(r => r.url().includes('/v1/labels/alpha/pending')); await page.locator('#domain').fill('alpha'); await response; await expect(page.locator('tbody tr')).toHaveCount(5); await expect(page.getByRole('row').filter({ hasText: 'beta-' })).toHaveCount(0); noErrors(state.consoleErrors) })
})

test('category edit → save → verify updated label', async ({ page }) => {
  const state = await workspace(page, { alpha: [row('C1')] })
  await test.step('open classification review', async () => { await page.goto('/#/review/C1'); await expect(page.getByRole('heading', { name: 'C1' })).toBeVisible(); await expect(page.getByRole('combobox', { name: 'Choose category' })).toHaveValue('PERSON') })
  await test.step('select and save ORG category', async () => { await page.getByRole('combobox', { name: 'Choose category' }).selectOption('ORG'); await expect(page.getByRole('button', { name: 'Relabel' })).toBeEnabled(); const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/alpha/items/C1/relabel')); await page.getByRole('button', { name: 'Relabel' }).click(); await response; expect(state.posts.at(-1)?.body).toMatchObject({ category: 'ORG', idempotency_token: 'rev-C1' }); await expect(page.getByRole('combobox', { name: 'Choose category' })).toHaveValue('ORG') })
  await test.step('verify the latest revision', async () => { await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct'); await expect(page.getByRole('button', { name: 'Approve recommendation (A)' })).toBeEnabled(); const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/verify')); await page.getByRole('button', { name: 'Approve recommendation (A)' }).click(); await response; expect(state.details.get('alpha/C1')?.category).toBe('ORG'); expect(state.posts.at(-1)?.body.label_id).toBe('C1'); noErrors(state.consoleErrors) })
})

test('settings guidelines appear in review', async ({ page }) => {
  const state = await workspace(page, { alpha: [row('G1')] })
  await test.step('load account and domain settings', async () => { await page.goto('/#/settings'); await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible(); await expect(page.getByText('Flow test tenant')).toBeVisible(); await expect(page.getByText('Active domain:')).toContainText('alpha') })
  await test.step('edit and save guidelines', async () => { const editor = page.getByRole('textbox', { name: 'Guidelines', exact: true }); await expect(editor).toBeEnabled(); await editor.fill('## Review rules\n- Check source evidence'); const response = page.waitForResponse(r => r.url().endsWith('/v1/domains/alpha/guidelines') && r.request().method() === 'PUT'); await page.getByRole('button', { name: 'Save guidelines' }).click(); await response; expect(state.posts.at(-1)?.body.guidelines).toContain('Check source evidence'); await expect(page.getByText('Guidelines saved.')).toBeVisible() })
  await test.step('open review guidelines', async () => { await queue(page).click(); await reviewRow(page, 'G1').click(); await page.getByRole('button', { name: 'Guidelines' }).click(); await expect(page.getByRole('region', { name: 'Annotation guidelines' })).toContainText('Check source evidence'); noErrors(state.consoleErrors) })
})

test('keyboard navigation opens a focused label and settings', async ({ page }) => {
  const state = await workspace(page, { alpha: Array.from({ length: 5 }, (_, n) => row(`K${n}`)) })
  await test.step('focus the queue surface', async () => { await page.goto('/#/queue'); await expect(page.locator('tbody tr')).toHaveCount(5); await page.getByRole('heading', { name: /Scored Queue/ }).click(); await expect(page.locator('tbody tr.queue-focused')).toContainText('K0') })
  await test.step('move down twice and up once', async () => { await page.keyboard.press('j'); await expect(page.locator('tbody tr.queue-focused')).toContainText('K1'); await page.keyboard.press('j'); await expect(page.locator('tbody tr.queue-focused')).toContainText('K2'); await page.keyboard.press('k'); await expect(page.locator('tbody tr.queue-focused')).toContainText('K1') })
  await test.step('open review and keyboard help', async () => { await page.keyboard.press('Enter'); await expect(page.getByRole('heading', { name: 'K1' })).toBeVisible(); await page.keyboard.press('?'); await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible(); await page.keyboard.press('Escape'); await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toHaveCount(0) })
  await test.step('use g then s for Settings', async () => { await page.keyboard.press('g'); await page.keyboard.press('s'); await expect(page).toHaveURL(/#\/settings$/); noErrors(state.consoleErrors) })
})

test('dark mode persists across screens and reload', async ({ page }) => {
  const state = await workspace(page)
  await test.step('start in light mode', async () => { await page.goto('/#/upload'); await expect(page.locator('html')).not.toHaveClass(/dark/); await expect(page.getByRole('button', { name: 'Toggle dark mode' })).toBeVisible() })
  await test.step('toggle dark and navigate', async () => { await page.getByRole('button', { name: 'Toggle dark mode' }).click(); await expect(page.locator('html')).toHaveClass(/dark/); await page.getByRole('link', { name: 'Settings' }).click(); await expect(page.locator('html')).toHaveClass(/dark/); await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible() })
  await test.step('reload and restore light mode', async () => { await page.reload(); await expect(page.locator('html')).toHaveClass(/dark/); expect(await page.evaluate(() => localStorage.getItem('dlj-theme'))).toBe('dark'); await page.getByRole('button', { name: 'Toggle dark mode' }).click(); await expect(page.locator('html')).not.toHaveClass(/dark/); noErrors(state.consoleErrors) })
})

test('NER span editing saves added and deleted entities', async ({ page }) => {
  const state = await workspace(page, { alpha: [row('N1')] })
  const original = { start: 0, end: 10, label: 'PERSON', text: 'John Smith' }
  state.details.set('alpha/N1', { ...detail('alpha', row('N1')), text: 'John Smith at Acme', content: { content_type: 'text_ner', spans: [original], tags: [], image_url: null } })
  await test.step('show the existing entity', async () => { await page.goto('/#/review/N1'); await expect(page.locator('mark[aria-label^="PERSON: John Smith"]')).toBeVisible(); await expect(page.getByRole('region', { name: 'Source text' })).toContainText('Acme') })
  await test.step('drag across Acme and choose ORG', async () => {
    const points = await page.evaluate(() => {
      const node = [...document.querySelectorAll('[data-ner-text]')].find(element => element.textContent?.includes('Acme'))!.firstChild!
      const index = node.textContent!.indexOf('Acme')
      const edge = (offset: number) => { const range = document.createRange(); range.setStart(node, offset); range.collapse(true); const rect = range.getBoundingClientRect(); return { x: rect.x, y: rect.y + rect.height / 2 } }
      return { start: edge(index), end: edge(index + 4) }
    })
    await page.mouse.move(points.start.x + 1, points.start.y)
    await page.mouse.down()
    await page.mouse.move(points.end.x - 1, points.end.y, { steps: 8 })
    await page.mouse.up()
    await expect(page.getByRole('dialog', { name: 'Choose entity type' })).toBeVisible()
    await page.getByRole('dialog', { name: 'Choose entity type' }).getByRole('button', { name: 'ORG' }).click()
    await expect(page.locator('mark[aria-label^="ORG: Acme"]')).toBeVisible()
    await expect(page.getByText('Unsaved changes')).toBeVisible()
  })
  await test.step('delete the prior entity and save spans', async () => { await page.locator('mark[aria-label^="PERSON: John Smith"]').click(); await page.getByRole('button', { name: 'Delete' }).click(); await expect(page.locator('mark[aria-label^="PERSON: John Smith"]')).toHaveCount(0); const response = page.waitForResponse(r => r.url().endsWith('/v1/labels/alpha/items/N1/relabel')); await page.getByRole('button', { name: 'Save Spans' }).click(); await response; expect(state.posts.at(-1)?.body.spans).toEqual([{ start: 14, end: 18, label: 'ORG', text: 'Acme' }]); await expect(page.getByText('Spans saved.')).toBeVisible(); noErrors(state.consoleErrors) })
})

test('queue error clears stale rows and recovers on refresh', async ({ page }) => {
  const state = await workspace(page, { alpha: [row('R1')] })
  let fail = false
  await page.route('**/v1/labels/alpha/pending*', async route => { if (fail) await route.fulfill({ status: 500, json: { detail: 'Temporary outage' } }); else await route.fallback() })
  await test.step('load a healthy queue', async () => { await page.goto('/#/queue'); await expect(page.getByRole('row').filter({ hasText: 'R1' })).toBeVisible() })
  await test.step('show error without stale data', async () => { fail = true; const response = page.waitForResponse(r => r.url().includes('/v1/labels/alpha/pending') && r.status() === 500); await page.getByRole('button', { name: 'Refresh' }).click(); await response; await expect(page.locator('.error')).toContainText('Temporary outage'); await expect(page.locator('tbody tr')).toHaveCount(0) })
  await test.step('retry successfully', async () => { fail = false; const response = page.waitForResponse(r => r.url().includes('/v1/labels/alpha/pending') && r.status() === 200); await page.getByRole('button', { name: 'Refresh' }).click(); await response; await expect(page.getByRole('row').filter({ hasText: 'R1' })).toBeVisible(); await expect(page.locator('.error')).toHaveCount(0); noErrors(state.consoleErrors) })
})
