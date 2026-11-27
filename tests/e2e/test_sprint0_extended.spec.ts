import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createInterface } from 'node:readline'
import { randomUUID } from 'node:crypto'
import { expect, test as base, type Page } from '@playwright/test'

type Server = { url: string; key: string; autonomous: string }
const test = base.extend<{}, { server: Server }>({
  server: [async ({}, use) => {
    const child = spawn('python', ['-u', '-m', 'tests.sprint0_browser_server'], { stdio: ['pipe', 'pipe', 'inherit'] })
    const exited = once(child, 'exit')
    const lines = createInterface({ input: child.stdout! })
    try {
      const next = await Promise.race([once(lines, 'line'), exited.then(() => { throw Error('PostgreSQL fixture failed to start') })])
      await use(JSON.parse(String(next[0])))
    } finally {
      child.stdin!.end(); await exited; lines.close()
    }
  }, { scope: 'worker', timeout: 120_000 }],
})

test('quoted CSV and a lost batch response preserve exactly one upload', async ({ page, server }) => {
  await open(page, server, 'quickstart')
  await page.getByRole('button', { name: 'Create project' }).click()
  await page.locator('input[type=file]').setInputFiles({
    name: 'labels.csv', mimeType: 'text/csv', buffer: Buffer.from('"Acme, Inc.",metadata\nScience report,metadata'),
  })
  await expect(page.getByLabel('One item per line')).toHaveValue('Acme, Inc.\nScience report')
  const requests: string[] = []
  let projectId = ''
  await page.route('**/labels/batch', async route => {
    requests.push(route.request().postData()!)
    projectId = new URL(route.request().url()).pathname.split('/')[3]
    if (requests.length === 1) {
      const committed = await route.fetch()
      expect(committed.ok()).toBeTruthy()
      await route.abort('failed')
    } else await route.continue()
  })
  const lostResponse = page.waitForEvent('requestfailed', r => r.url().endsWith('/labels/batch'))
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  await lostResponse
  await expect(page.getByRole('alert')).toBeVisible()
  const replay = page.waitForResponse(r => r.url().endsWith('/labels/batch'))
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  expect((await replay).ok()).toBeTruthy()
  await expect(page.getByText('2 items uploaded ✓')).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[0]).toBe(requests[1])
  const batch = await (await api(page, server, '/' + projectId + '/next-batch')).json()
  expect(batch.total_pending).toBe(2)
  expect(batch.items.map((r: { text_preview: string }) => r.text_preview).sort()).toEqual(['Acme, Inc.', 'Science report'])
})

test('oversized walkthrough input stays editable without submitting a partial batch', async ({ page, server }) => {
  await open(page, server, 'quickstart')
  await page.getByRole('button', {name:'Create project'}).click()
  let writes = 0
  page.on('request', request => { if (request.url().endsWith('/labels/batch')) writes++ })
  await page.getByLabel('One item per line').fill(Array(101).fill('row').join('\n'))
  await page.getByRole('button', {name:'Upload', exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('between 1 and 100')
  expect(writes).toBe(0)
  await page.getByLabel('One item per line').fill('corrected')
  await page.getByRole('button', {name:'Upload', exact:true}).click()
  await expect(page.getByText('1 item uploaded ✓')).toBeVisible()
  expect(writes).toBe(1)
})

test.beforeEach(async ({ page, server }) => {
  await page.addInitScript(key => localStorage.setItem('rgi-api-key', key), server.key)
})

async function api(page: Page, server: Server, path: string, data?: unknown) {
  const result = await page.request.fetch(server.url + '/v1/projects' + path, {
    method: data === undefined ? 'GET' : 'POST', headers: { 'X-Api-Key': server.key }, data,
  })
  expect(result.ok(), path + ' ' + result.status()).toBeTruthy()
  return result
}
async function project(page: Page, server: Server) {
  const alias = 'sprint-' + randomUUID()
  return (await (await api(page, server, '', { name: alias, public_domain_id: alias,
    categories: ['A', 'B'], factors: ['quality', 'difficulty'], actions: ['approve', 'reject'] })).json()).id as string
}
async function upload(page: Page, server: Server, id: string, count: number) {
  const items = Array.from({ length: count }, (_, index) => ({ label_id: 'item-' + index,
    category: index % 2 ? 'B' : 'A', text: 'Source ' + index,
    factors: { quality: index / count, difficulty: .2 } }))
  await api(page, server, '/' + id + '/labels/batch', { request_key: randomUUID(), items })
}
async function train(page: Page, server: Server, id: string, count: number) {
  const ids = Array.from({ length: count }, (_, index) => 'item-' + index)
  const result = await api(page, server, '/' + id + '/labels/bulk-verify', { label_ids: ids, outcome: true, action: 'approve' })
  expect((await result.json()).processed).toBe(count)
}
async function open(page: Page, server: Server, route: string) {
  await page.goto(server.url + '/#/' + route)
}
const badge = (page: Page) => page.getByRole('status', { name: /Quality SLA/ })
const smart = (page: Page) => page.getByRole('checkbox', { name: 'Smart Queue' })
async function review(page: Page, correct = true) {
  // The review screen loads canonical detail from PostgreSQL after each navigation.
  await expect(page.getByText('Factor signals', { exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByLabel('Known outcome').selectOption(correct ? 'correct' : 'incorrect')
  const response = page.waitForResponse(r => r.url().endsWith('/labels/verify'))
  await page.getByRole('button', { name: /Approve recommendation/ }).click()
  expect((await response).status()).toBe(200)
}
async function walkthrough(page: Page, server: Server) {
  await open(page, server, 'quickstart')
  const name = 'Demo ' + randomUUID()
  await page.getByLabel('Project name').fill(name)
  await page.getByRole('button', { name: 'Create project' }).click()
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  await expect(page.getByText('5 items uploaded ✓')).toBeVisible()
  await page.locator('.quickstart-items button').first().click()
  await expect(page.locator('.quickstart-factors .factor')).toHaveCount(6)
  await page.getByRole('button', { name: 'Verify', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'What’s next' })).toBeVisible()
  await page.getByRole('link', { name: 'Project dashboard' }).click()
  await expect(badge(page)).toContainText('activates after 50')
  await expect(page.locator('#project-chooser option:checked')).toHaveText(name)
}
async function importModels(page: Page, server: Server, id: string, names: string[]) {
  const items = names.map((label, i) => ({ label_id: label, text: label, source: 'model-a', model_version: 'v1',
    category: 'A', annotator_id: 'model-reviewer', factors: { quality: .9, difficulty: .1 }, model_confidence: i ? .2 : .99 }))
  return (await (await api(page, server, '/' + id + '/predictions', { request_key: randomUUID(), items })).json()).results
}

test('test_full_labeling_flow', async ({ page, server }) => {
  const id = await project(page, server)
  await upload(page, server, id, 2)
  await open(page, server, 'projects/' + id + '/queue')
  await smart(page).check()
  await page.getByRole('link', { name: /Review →/ }).first().click()
  const first = page.url()
  await review(page)
  await expect(page).not.toHaveURL(first)
  await review(page, false)
  const dashboard = Promise.all(['overview', 'corrections', 'compounding'].map(section =>
    page.waitForResponse(response => new URL(response.url()).pathname === `/v1/projects/${id}/dashboard/${section}`)))
  await open(page, server, 'projects/' + id + '/dashboard')
  for (const response of await dashboard) expect(response.ok()).toBe(true)
  await expect(page.getByText('50.0%', { exact: true }).first()).toBeVisible()
  const sla = await (await api(page, server, '/' + id + '/sla')).json()
  expect([sla.verified_count, sla.current_accuracy]).toEqual([2, 50])
})

test('test_smart_queue_vs_random_ordering', async ({ page, server }) => {
  const id = await project(page, server)
  await upload(page, server, id, 45); await train(page, server, id, 20)
  await open(page, server, 'projects/' + id + '/queue')
  await expect(smart(page)).toBeChecked()
  const displayed = page.locator('tbody tr td strong').filter({ hasText: /^item-/ })
  const priority = (await (await api(page, server, '/' + id + '/next-batch')).json()).items.map((row: {id: string}) => row.id)
  await expect(displayed).toHaveText(priority)
  await smart(page).uncheck()
  const original = (await (await api(page, server, '/' + id + '/labels/pending?sort_by=scored_at&sort_order=asc')).json()).map((row: {label_id: string}) => row.label_id)
  await expect(displayed).toHaveText(original)
  expect(priority).not.toEqual(original)
  await page.reload()
  await expect(displayed).toHaveText(original, { timeout: 30_000 })
  await smart(page).check(); await expect(displayed).toHaveText(priority, { timeout: 30_000 })
})

test('test_sla_badge_lifecycle', async ({ page, server }) => {
  const id = await project(page, server)
  await open(page, server, 'projects/' + id + '/dashboard')
  await expect(badge(page)).toContainText('activates after 50')
  await upload(page, server, id, 52); await train(page, server, id, 52)
  await page.reload()
  const result = await (await api(page, server, '/' + id + '/sla')).json()
  expect(result.gate_status).toBe('safe')
  await expect(badge(page)).toContainText('≥' + result.floor_pct.toFixed(1) + '%')
  await expect(badge(page)).toContainText('100.0% current')
})

test('test_quickstart_complete_flow', async ({ page, server }) => {
  await walkthrough(page, server)
})

test('test_prediction_review_then_sla_check', async ({ page, server }) => {
  const id = server.autonomous
  const results = await importModels(page, server, id, ['auto-eligible', 'accept-me', 'correct-me'])
  expect(results.map((r: {state: string}) => r.state)).toEqual(['auto_approved', 'pending', 'pending'])
  await open(page, server, 'projects/' + id + '/predictions')
  await expect(page.getByRole('row').filter({ hasText: 'auto-eligible' })).toBeVisible()
  await page.getByRole('row').filter({ hasText: 'accept-me' }).click()
  await page.getByRole('button', { name: /Accept/ }).click()
  await expect(page.getByText('Prediction accepted.')).toBeVisible()
  await open(page, server, 'projects/' + id + '/dashboard'); await expect(badge(page)).toHaveClass(/sla-safe/)
  await open(page, server, 'projects/' + id + '/predictions')
  await page.getByRole('row').filter({ hasText: 'correct-me' }).click()
  await page.getByRole('button', { name: /Correct/ }).click(); await page.getByRole('dialog').getByRole('combobox', { name: 'Category' }).selectOption('B')
  await page.getByRole('button', { name: 'Confirm correction' }).click()
  await expect(page.getByText('Correction recorded.')).toBeVisible()
  await open(page, server, 'projects/' + id + '/dashboard')
  const result = await (await api(page, server, '/' + id + '/sla')).json()
  expect(result.current_accuracy).toBeLessThan(100)
  await expect(badge(page)).toContainText(result.current_accuracy.toFixed(1) + '% current')
})

test('test_webhook_fires_after_verification', async ({ page, server }) => {
  const id = await project(page, server)
  await open(page, server, 'projects/' + id + '/integrations')
  await page.getByRole('button', { name: 'Add webhook' }).click()
  await page.getByLabel('HTTPS URL').fill('https://webhook.example.test/review')
  await page.getByLabel('label.verified', { exact: true }).check()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Save this signing secret now.', {exact: false})).toBeVisible()
  await upload(page, server, id, 1)
  await open(page, server, 'projects/' + id + '/review/item-0'); await review(page)
  await expect.poll(async () => (await (await api(page, server, '/' + id + '/webhooks/health')).json()).healthy).toBe(1)
  await open(page, server, 'projects/' + id + '/integrations')
  await expect(page.getByText('1/1 healthy')).toBeVisible()
  await page.getByRole('button', {name: 'View delivery history'}).click()
  await expect(page.locator('.attempt-history tbody tr')).toContainText('label.verified')
  await expect(page.locator('.attempt-history tbody tr')).toContainText('204')
})

test('test_guide_to_quickstart_crosslink', async ({ page, server }) => {
  await open(page, server, 'docs')
  await page.getByRole('link', { name: 'Start the interactive quickstart' }).click()
  await page.getByRole('button', {name: 'Create project'}).click()
  await expect(page.getByRole('heading', {name: 'Upload sample data'})).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', {name: 'Getting Started'})).toBeVisible()
})

test('test_export_after_smart_sampling_session', async ({ page, server }) => {
  const id = await project(page, server)
  await upload(page, server, id, 26); await train(page, server, id, 20)
  const chosen: string[] = []
  for (let i = 0; i < 5; i++) {
    await open(page, server, 'projects/' + id + '/queue')
    await expect(smart(page)).toBeChecked()
    const first = page.locator('tbody tr').first()
    const label = await first.locator('strong').filter({hasText:/^item-/}).innerText()
    chosen.push(label)
    await first.getByRole('link').click(); await review(page)
  }
  const data = (await (await api(page, server, '/' + id + '/export?format=jsonl')).text()).trim().split('\n').map(line => JSON.parse(line))
  expect(new Set(chosen).size).toBe(5)
  for (const label of chosen) {
    expect(data.find(r => r.current_label_id === label)).toMatchObject({root_label_id: label, review_state: 'verified', verified_outcome: true})
  }
})

test('test_project_switch_preserves_state', async ({ page, server }) => {
  const a = await project(page, server), b = await project(page, server)
  await upload(page, server, a, 50); await train(page, server, a, 50)
  await open(page, server, 'projects/' + a + '/dashboard')
  await expect(badge(page)).toHaveClass(/sla-safe/)
  const original = await badge(page).innerText()
  await page.locator('#project-chooser').selectOption(b)
  await page.getByRole('link', {name:/Dashboard/}).click()
  await expect(badge(page)).toHaveClass(/sla-inactive/)
  await page.locator('#project-chooser').selectOption(a)
  await page.getByRole('link', {name:/Dashboard/}).click()
  await expect(badge(page)).toHaveText(original.replace(/\n/g, ''), {useInnerText:false})
})

test('test_keyboard_shortcuts_in_review_queue', async ({ page, server }) => {
  const id = await project(page, server)
  await importModels(page, server, id, ['key-one', 'key-two', 'key-three'])
  await open(page, server, 'projects/' + id + '/predictions')
  await expect(page.locator('tbody tr td:first-child')).toHaveCount(3)
  const labels = await page.locator('tbody tr td:first-child').allTextContents()
  expect(labels).toHaveLength(3)
  await page.getByRole('row').filter({hasText:labels[0]}).click()
  const card = page.getByLabel('Prediction review card')
  await card.focus(); await page.keyboard.press('a')
  await expect(page.getByText('Prediction accepted.')).toBeVisible()
  await expect(card.getByRole('heading', {name:labels[1]})).toBeVisible()
  await card.focus(); await page.keyboard.press('ArrowRight')
  await expect(card.getByRole('heading', {name:labels[2]})).toBeVisible()
  await card.focus(); await page.keyboard.press('c')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.getByRole('row').filter({hasText:labels[0]}).click()
  await card.focus(); await page.keyboard.press('r')
  await expect(page.getByText('Prediction reopened.')).toBeVisible()
})

test('test_mobile_responsive_dashboard', async ({ page, server }) => {
  await page.setViewportSize({width:400,height:820})
  const id = await project(page, server)
  await open(page, server, 'projects/' + id + '/dashboard')
  await expect(badge(page)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400)
  await page.getByRole('button', {name:'Toggle navigation'}).click()
  await page.getByRole('link', {name:/Scored Queue/}).click(); await expect(smart(page)).toBeVisible()
  await walkthrough(page, server)
})

test('test_sla_badge_tooltip', async ({page, server}) => {
  await open(page, server, 'projects/' + server.autonomous + '/dashboard')
  await badge(page).hover()
  const result = await (await api(page, server, '/' + server.autonomous + '/sla')).json()
  await expect(badge(page)).toHaveAttribute('title', 'Margin: ' + result.margin.toFixed(1) + ' percentage points above the floor')
})

test('test_next_batch_loading_state', async ({page, server}) => {
  const id = await project(page, server)
  await upload(page, server, id, 2)
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  let arrived!: () => void
  const ranked = new Promise<void>(resolve => { arrived = resolve })
  await page.route('**/next-batch?**', async route => {
    if (new URL(route.request().url()).searchParams.get('n') === '1') { await route.continue(); return }
    const response = await route.fetch()
    expect(response.ok()).toBeTruthy()
    arrived()
    await held
    await route.fulfill({response})
  })
  await open(page, server, 'projects/' + id + '/queue')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await smart(page).check()
  await ranked
  try { await expect(page.getByRole('status', {name:'Loading',exact:true})).toBeVisible() }
  finally { release() }
  await expect(page.locator('tbody tr')).toHaveCount(2)
})

test('test_quickstart_step_validation', async ({page, server}) => {
  await open(page, server, 'quickstart')
  await page.getByLabel('Project name').fill('   ')
  await expect(page.getByRole('button', {name:'Create project'})).toBeDisabled()
  await page.getByLabel('Project name').fill('Valid name')
  await expect(page.getByRole('button', {name:'Create project'})).toBeEnabled()
})

test('changing the active domain during project creation releases the walkthrough controls', async ({ page, server }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/projects', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return }
    await held
    await route.abort().catch(() => {})
  })
  await open(page, server, 'quickstart')
  const started = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/v1/projects'))
  await page.getByRole('button', { name: 'Create project' }).click()
  await started
  await page.locator('#domain').fill('new-domain')
  release()
  await expect(page.getByRole('button', { name:'Create project' })).toBeEnabled()
  await expect(page.getByRole('heading', { name:'Upload sample data' })).toHaveCount(0)
})

test('test_dashboard_no_console_errors', async ({page, server}) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
  const id = await project(page, server)
  await open(page, server, 'projects/' + id + '/dashboard')
  await expect(badge(page)).toBeVisible({ timeout: 30_000 })
  expect(errors).toEqual([])
})
