import { expect, test, type Page, type Route } from '@playwright/test'

const project = { id: '11111111-1111-4111-8111-111111111111', public_domain_id: 'prompt-f', name: 'Prompt F', status: 'active', settings_version: 1, role: 'owner' }
const prediction = { id: '22222222-2222-4222-8222-222222222222', label_id: 'pred-1', spans: [], state: 'pending', prediction_state: 'pending_review', origin: 'prediction', current_label_log_id: '33333333-3333-4333-8333-333333333333', source: 'model-f', model_version: 'v1', model_confidence: .96, dlj_confidence: .84, category: 'A', action: 'approve', confidence: .84, recommendation: 'approve', text: 'A model prediction awaiting human review.', factors: { quality: .8, difficulty: .2 }, annotator_id: 'model-reviewer', scored_at: '2026-11-26T12:00:00Z', decision_version: 1, categories: ['A', 'B'], actions: ['approve', 'reject'], assessment: null as string | null }

async function identity(page: Page) {
  await page.addInitScript(() => localStorage.setItem('rgi-api-key', 'prompt-f-key'))
}

async function base(route: Route) {
  const request = route.request(), url = new URL(request.url())
  if (url.pathname === '/v1/projects') { await route.fulfill({ json: [project] }); return true }
  return false
}

async function predictionApi(page: Page, spans: {start:number; end:number; label:string; text:string}[] = []) {
  await identity(page)
  const posts: { path: string; body: any }[] = []
  let current = { ...prediction, spans }
  await page.route('**/v1/**', async route => {
    if (await base(route)) return
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    const body = request.postDataJSON?.() as any
    if (request.method() !== 'GET') posts.push({ path, body })
    if (path.endsWith('/predictions') && request.method() === 'GET') return route.fulfill({ json: { items: [current], total: 1, limit: 100, offset: 0 } })
    if (path.endsWith('/labels/pending')) return route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } })
    if (path.endsWith('/review')) { current = { ...current, state: 'human_reviewed', prediction_state: body.action === 'correct' ? 'corrected' : 'accepted', assessment: body.action === 'correct' ? 'incorrect' : 'correct', decision_version: 2 }; return route.fulfill({ json: current }) }
    if (path.endsWith('/reopen')) { current = { ...current, state: 'pending', prediction_state: 'reopened', decision_version: current.decision_version + 1 }; return route.fulfill({ json: current }) }
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  return { posts, current: () => current }
}

type Hook = { id: string; project_id: string; url: string; subscribed_events: string[]; active: boolean; key_version: number; destination_version: number; signing_secret_masked: string; rotated_at: string | null; created_at: string; updated_at: string; signing_secret?: string }
async function integrationApi(page: Page) {
  await identity(page)
  let hooks: Hook[] = [{ id: '44444444-4444-4444-8444-444444444444', project_id: project.id, url: 'https://hooks.example.test/one', subscribed_events: ['label.verified'], active: true, key_version: 1, destination_version: 1, signing_secret_masked: 'dlj_whsec_****', rotated_at: null, created_at: '2026-11-26T12:00:00Z', updated_at: '2026-11-26T12:00:00Z' }]
  await page.route('**/v1/**', async route => {
    if (await base(route)) return
    const request = route.request(), url = new URL(request.url()), path = url.pathname, body = request.postDataJSON?.() as any
    if (path.endsWith('/webhooks/health')) return route.fulfill({ json: { total: hooks.length, healthy: hooks.length, retrying: 0, failing: 0, items: hooks.map(hook => ({ webhook_id: hook.id, status: 'healthy', active: hook.active, last_delivery_state: 'delivered', last_status: 204, last_delivered_at: hook.updated_at, next_retry_at: null })) } })
    if (path.endsWith('/deliveries')) return route.fulfill({ json: { total: 1, limit: 20, offset: 0, items: [], attempt_history: [{ delivery_id: 'd1', event_id: 'e1', event_type: 'label.verified', attempt_no: 1, timestamp: '2026-11-26T12:00:00Z', http_status: 204, outcome: 'success', response_time_ms: 18, next_retry_at: null, error_summary: null }] } })
    if (path.endsWith('/rotate')) { const hook = hooks[0] = { ...hooks[0], key_version: 2, rotated_at: '2026-11-26T13:00:00Z', signing_secret: 'new-secret' }; return route.fulfill({ json: hook }) }
    if (path.endsWith('/test')) return route.fulfill({ status: 201, json: { event_id: 'e1', delivery_id: 'd1' } })
    if (path.endsWith('/webhooks') && request.method() === 'GET') return route.fulfill({ json: hooks })
    if (path.endsWith('/webhooks') && request.method() === 'POST') { const hook: Hook = { id: '55555555-5555-4555-8555-555555555555', project_id: project.id, url: body.url, subscribed_events: body.subscribed_events, active: true, key_version: 1, destination_version: 1, signing_secret_masked: 'dlj_whsec_****', rotated_at: null, created_at: '2026-11-26T12:00:00Z', updated_at: '2026-11-26T12:00:00Z', signing_secret: 'shown-once' }; hooks = [...hooks, hook]; return route.fulfill({ status: 201, json: hook }) }
    if (request.method() === 'PATCH') { hooks[0] = { ...hooks[0], ...body }; return route.fulfill({ json: hooks[0] }) }
    if (request.method() === 'DELETE') { hooks[0] = { ...hooks[0], active: false }; return route.fulfill({ json: hooks[0] }) }
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  return { hooks: () => hooks }
}

test('guide page renders', async ({ page }) => {
  await page.goto('/#/docs')
  await expect(page.getByRole('heading', { name: 'Build a reliable review loop' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Webhooks' })).toBeVisible()
})

test('guide sidebar navigation', async ({ page }) => {
  await page.goto('/#/docs')
  await page.getByRole('button', { name: 'Python Client' }).click()
  await expect(page.getByRole('heading', { name: 'Python Client' })).toBeInViewport()
})

test('guide responsive navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/#/docs')
  await expect(page.getByRole('combobox', { name: 'Guide section' })).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Guide sections' })).toBeHidden()
})

test('guide client download link', async ({ page }) => {
  await page.goto('/#/docs')
  await expect(page.getByRole('link', { name: 'Download dlj_client.py' })).toHaveAttribute('href', '/dlj_client.py')
})

test('prediction review queue', async ({ page }) => {
  await predictionApi(page); await page.goto(`/#/projects/${project.id}/predictions`)
  await expect(page.getByRole('row').filter({ hasText: 'A model prediction' })).toBeVisible()
})

test('prediction review accept', async ({ page }) => {
  const api = await predictionApi(page); await page.goto(`/#/projects/${project.id}/predictions`)
  await page.getByRole('row').filter({ hasText: 'A model prediction' }).click(); await page.getByRole('button', { name: /Accept/ }).click()
  await expect.poll(() => api.posts.some(post => post.path.endsWith('/review') && post.body.action === 'accept')).toBeTruthy()
})

test('prediction review correct', async ({ page }) => {
  const api = await predictionApi(page); await page.goto(`/#/projects/${project.id}/predictions`)
  await page.getByRole('row').filter({ hasText: 'A model prediction' }).click(); await page.getByRole('button', { name: /Correct/ }).click()
  await page.getByLabel('Category').selectOption('B'); await page.getByLabel('Action').selectOption('reject'); await page.getByRole('button', { name: 'Confirm correction' }).click()
  await expect.poll(() => api.posts.some(post => post.body.action === 'correct' && post.body.category === 'B' && post.body.actual_action === 'reject')).toBeTruthy()
})

test('prediction review keyboard is focus scoped', async ({ page }) => {
  const api = await predictionApi(page); await page.goto(`/#/projects/${project.id}/predictions`)
  await page.getByRole('row').filter({ hasText: 'A model prediction' }).click(); await page.locator('body').click({ position: { x: 5, y: 5 } }); await page.keyboard.press('a')
  expect(api.posts).toHaveLength(0)
  await page.getByLabel('Prediction review card').focus(); await page.keyboard.press('Control+a'); expect(api.posts).toHaveLength(0); await page.keyboard.press('a'); await expect.poll(() => api.posts.length).toBe(1)
})

test('NER verification requires acknowledgement of the displayed spans', async ({page}) => {
  const api = await predictionApi(page, [{ start: 0, end: 1, label: 'A', text: 'A' }])
  await page.goto(`/#/projects/${project.id}/predictions`)
  await page.getByRole('row').filter({hasText: 'A model prediction'}).click()
  const accept = page.getByRole('button', {name: /Accept/})
  await expect(accept).toBeDisabled()
  await expect(page.locator('mark')).toBeVisible()
  await page.getByLabel('I reviewed these spans').check()
  await accept.click()
  await expect.poll(() => api.posts[0]?.body.human_spans_reviewed).toBe(true)
})

test('integrations webhook list', async ({ page }) => {
  await integrationApi(page); await page.goto(`/#/projects/${project.id}/integrations`)
  await expect(page.getByText('https://hooks.example.test/one')).toBeVisible()
})

test('integrations add webhook', async ({ page }) => {
  const api = await integrationApi(page); await page.goto(`/#/projects/${project.id}/integrations`)
  await page.getByRole('button', { name: 'Add webhook' }).click(); await page.getByLabel('HTTPS URL').fill('https://hooks.example.test/two'); await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('shown-once')).toBeVisible(); expect(api.hooks()).toHaveLength(2)
})

test('integrations edit, test and deactivate', async ({ page }) => {
  await integrationApi(page)
  page.on('dialog', dialog => dialog.accept())
  await page.goto(`/#/projects/${project.id}/integrations`)
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByLabel('HTTPS URL').fill('https://hooks.example.test/changed')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('https://hooks.example.test/changed')).toBeVisible()
  await page.getByRole('button', { name: 'Test send' }).click()
  await expect(page.getByText('Test event queued.')).toBeVisible()
  await page.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByRole('button', { name: 'Test send' })).toBeDisabled()
})

test('integrations delivery health', async ({ page }) => {
  await integrationApi(page); await page.goto(`/#/projects/${project.id}/integrations`)
  await expect(page.getByText('1/1 healthy')).toBeVisible(); await page.getByRole('button', { name: /View delivery history/ }).click(); await expect(page.getByText('18 ms')).toBeVisible()
})

test('integrations secret rotation', async ({ page }) => {
  await integrationApi(page); page.on('dialog', dialog => dialog.accept()); await page.goto(`/#/projects/${project.id}/integrations`)
  await page.getByRole('button', { name: 'Rotate secret' }).click(); await expect(page.getByText('new-secret')).toBeVisible(); await expect(page.getByText(/key version 2/)).toBeVisible()
})
