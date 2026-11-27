import { expect, test, type Page, type Route } from '@playwright/test'

const project = { id: '11111111-1111-4111-8111-111111111111', public_domain_id: 'sprint-zero', name: 'Sprint Zero', status: 'active', settings_version: 1, role: 'owner' }

async function identity(page: Page) {
  await page.addInitScript(() => localStorage.setItem('rgi-api-key', 'sprint-zero-key'))
}

async function projectBase(route: Route) {
  const url = new URL(route.request().url())
  if (url.pathname === '/v1/projects' && route.request().method() === 'GET') {
    await route.fulfill({ json: [project] }); return true
  }
  return false
}

test('smart queue toggle changes item ordering', async ({ page }) => {
  await identity(page)
  await page.route('**/v1/**', async route => {
    if (await projectBase(route)) return
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/autonomy')) return route.fulfill({ json: { domain_id: 'sprint-zero', overall_tier: 'red', categories: [{ category: 'A', tier: 'red', verified_count: 20, accuracy: .8, conservation_gate_pass: true, conservation_reason: null, next_tier: 'amber', next_tier_requirements: null, recommended_action_policy: 'review' }] } })
    if (path.endsWith('/next-batch')) return route.fulfill({ json: { strategy: 'centroid_distance', total_pending: 2, items: [
      { id: 'far-item', text_preview: 'Far from learned examples', centroid_distance: .91, category: 'A', priority_rank: 1, annotator_id: null, recommended_action: 'approve', confidence: .55 },
      { id: 'near-item', text_preview: 'Near learned examples', centroid_distance: .12, category: 'A', priority_rank: 2, annotator_id: null, recommended_action: 'approve', confidence: .92 },
    ] } })
    if (path.endsWith('/labels/pending')) return route.fulfill({ headers: { 'X-Total-Count': '2' }, json: [
      { label_id: 'near-item', category: 'A', annotator_id: null, factors: {}, text_preview: 'Near', recommended_action: 'approve', confidence: .92 },
      { label_id: 'far-item', category: 'A', annotator_id: null, factors: {}, text_preview: 'Far', recommended_action: 'approve', confidence: .55 },
    ] })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  await page.goto(`/#/projects/${project.id}/queue`)
  const rows = page.locator('tbody tr')
  await expect(rows.first()).toContainText('far-item')
  await expect(page.getByText('Smart priority: highest centroid distance first.')).toBeVisible()
  await page.getByRole('checkbox', { name: 'Smart Queue' }).uncheck()
  await expect(rows.first()).toContainText('near-item')
})

test('SLA badge renders on dashboard', async ({ page }) => {
  await identity(page)
  await page.route('**/v1/**', async route => {
    if (await projectBase(route)) return
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/dashboard/overview')) return route.fulfill({ json: { domain_id: 'sprint-zero', overall_accuracy: .91, total_verified: 80, total_labels: 100, categories: [], inversion: null, compounding_curve: [], generated_at: '2026-11-26T00:00:00Z' } })
    if (path.endsWith('/dashboard/corrections')) return route.fulfill({ json: { domain_id: 'sprint-zero', total_corrections: 0, correction_rate: null, patterns: [], top_pattern: null } })
    if (path.endsWith('/dashboard/compounding')) return route.fulfill({ json: { domain_id: 'sprint-zero', category: null, points: [], baseline_accuracy: .8, current_accuracy: .91, improvement: 11 } })
    if (path.endsWith('/dashboard/iaa')) return route.fulfill({ json: { pairs: [], overall_kappa: null, total_overlapping_labels: 0 } })
    if (path.endsWith('/sla')) return route.fulfill({ json: { floor_pct: 71.2, current_accuracy: 91.2, margin: 20, gate_status: 'safe', auto_approve_active: true, verified_count: 80, min_verified_for_sla: 50 } })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  await page.goto(`/#/projects/${project.id}/dashboard`)
  await expect(page.getByRole('status', { name: /Quality SLA/ })).toContainText('≥71.2% guaranteed')
})

async function quickstartApi(page: Page) {
  await identity(page)
  const posts: { path: string; body: Record<string, unknown> }[] = []
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === '/v1/projects' && request.method() === 'GET') return route.fulfill({ json: [] })
    const body = (request.postDataJSON?.() ?? {}) as Record<string, unknown>
    if (request.method() === 'POST') posts.push({ path, body })
    if (path === '/v1/projects') return route.fulfill({ status: 201, json: project })
    if (path.endsWith('/labels/batch')) {
      const items = body.items as { label_id: string; category: string; factors: Record<string, number> }[]
      return route.fulfill({ json: { batch_size: items.length, results: items.map(item => ({ label_id: item.label_id, decision_id: `d-${item.label_id}`, recommended_action: 'approve', confidence: .84, factors_used: item.factors, category: item.category, conservation_status: 'warmup', tier: 'red', action_policy: 'review', auto_accepted: false, tier_status: { tier: 'red', category: item.category, verified_count: 0, accuracy: null, conservation_gate_pass: true, conservation_reason: null, next_tier: 'amber', next_tier_requirements: null, recommended_action_policy: 'review' } })) } })
    }
    if (path.endsWith('/labels/verify')) return route.fulfill({ json: { label_id: body.label_id, action_taken: body.actual_action, was_correct: body.verified_outcome, engine_updated: true, new_accuracy: 1 } })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  return posts
}

test('quickstart completes all five steps', async ({ page }) => {
  await quickstartApi(page); await page.goto('/#/quickstart')
  await page.getByRole('button', { name: 'Create project' }).click()
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  await expect(page.getByText('5 items uploaded ✓')).toBeVisible()
  await page.locator('.quickstart-items button').first().click()
  await expect(page.getByRole('heading', { name: 'Verify a label' })).toBeVisible()
  await page.getByRole('button', { name: 'Verify', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'What’s next' })).toBeVisible()
  await expect(page).toHaveURL(/#\/quickstart$/)
})

test('quickstart step one creates a real project', async ({ page }) => {
  const posts = await quickstartApi(page); await page.goto('/#/quickstart')
  await page.getByLabel('Project name').fill('My first project')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect.poll(() => posts.find(post => post.path === '/v1/projects')?.body.name).toBe('My first project')
  const body = posts.find(post => post.path === '/v1/projects')?.body
  expect(body?.categories).toEqual(['Technology', 'Business', 'Sports', 'Science'])
})
