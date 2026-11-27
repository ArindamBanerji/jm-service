import { expect, test, type Page } from '@playwright/test'

const id = '88888888-8888-4888-8888-888888888888'

type MockState = { guidelines: string; updated: string | null; version: number; reviewNote: string | null; verified: boolean }

async function mockWorkspace(page: Page, overrides: Partial<MockState> = {}) {
  const state: MockState = { guidelines: '# Review policy\n- Check evidence\n- Escalate uncertainty',
    updated: '2026-11-26T10:00:00Z', version: 1, reviewNote: null, verified: false, ...overrides }
  await page.addInitScript(() => localStorage.setItem('rgi-api-key', 'notes-key'))
  await page.route('**/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (path === '/v1/projects' && request.method() === 'GET') return route.fulfill({ json: [{
      id, public_domain_id: 'notes-demo', name: 'Notes Demo', description: null,
      status: 'active', settings_version: state.version, role: 'owner',
    }] })
    if (path === `/v1/projects/${id}` && request.method() === 'GET') return route.fulfill({ json: {
      id, public_domain_id: 'notes-demo', name: 'Notes Demo', description: null,
      status: 'active', settings_version: state.version, role: 'owner', automation_enabled: false,
      confidence_floor: .95, guidelines: state.guidelines, guidelines_updated_at: state.updated,
    } })
    if (path === `/v1/projects/${id}` && request.method() === 'PATCH') {
      const body = request.postDataJSON() as { guidelines?: string | null }
      if ('guidelines' in body) { state.guidelines = body.guidelines ?? ''; state.updated = '2026-11-26T12:00:00Z' }
      state.version += 1
      return route.fulfill({ json: { id, settings_version: state.version, status: 'active' } })
    }
    if (path.endsWith('/guidelines')) return route.fulfill({ json: {
      guidelines: state.guidelines, guidelines_updated_at: state.updated,
    } })
    if (path.endsWith('/autonomy')) return route.fulfill({ json: { domain_id: 'notes-demo', overall_tier: 'amber', categories: [{
      category: 'A', tier: 'amber', verified_count: 0, accuracy: null,
      conservation_gate_pass: true, conservation_reason: null, next_tier: 'green',
      next_tier_requirements: '', recommended_action_policy: 'confirm',
    }] } })
    if (path.endsWith('/labels/items/L1')) return route.fulfill({ json: {
      domain_id: 'notes-demo', label_id: 'L1', category: 'A', annotator_id: 'ann-1',
      factors: { quality: .8, difficulty: .2 }, recommended_action: 'approve', confidence: .8,
      text: 'Example label', notes: 'Annotator context', review_notes: state.reviewNote,
      actual_action: state.verified ? 'approve' : null, verified_outcome: state.verified ? true : null,
      verified_at: state.verified ? '2026-11-26T12:00:00Z' : null,
      revision_id: '99999999-9999-4999-8999-999999999999', previous_category: null,
      status: 'scored', content: null,
    } })
    if (path.endsWith('/labels/verify')) {
      const body = request.postDataJSON() as { notes?: string }
      state.reviewNote = body.notes ?? null; state.verified = true
      return route.fulfill({ json: { label_id: 'L1', action_taken: 'approve', was_correct: true,
        engine_updated: true, new_accuracy: 1 } })
    }
    if (path.endsWith('/labels/pending')) return route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } })
    if (path.endsWith('/next-batch')) return route.fulfill({ json: {
      items: [{ id: 'L1', text_preview: 'Example label', centroid_distance: .4, category: 'A',
        priority_rank: 1, annotator_id: 'ann-1', recommended_action: 'approve', confidence: .8 }],
      strategy: 'centroid_distance', total_pending: 1, note: null,
    } })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${request.method()} ${path}` } })
  })
  return state
}

test('note field is available during verification', async ({ page }) => {
  await mockWorkspace(page)
  await page.goto(`/#/projects/${id}/review/L1`)
  await expect(page.getByRole('textbox', { name: 'Add a note (optional)' })).toBeVisible()
  await expect(page.getByText('0/500')).toBeVisible()
})

test('review note is saved and visible in label detail', async ({ page }) => {
  await mockWorkspace(page)
  await page.goto(`/#/projects/${id}/review/L1`)
  await page.getByRole('textbox', { name: 'Add a note (optional)' }).fill('Needs a second source check')
  await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct')
  await page.getByRole('button', { name: 'Approve recommendation (A)' }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/queue$`))
  await page.goto(`/#/projects/${id}/review/L1`)
  await expect(page.getByText('Needs a second source check')).toBeVisible()
})

test('project guidelines panel renders', async ({ page }) => {
  await mockWorkspace(page)
  await page.goto(`/#/projects/${id}/settings`)
  await expect(page.getByRole('heading', { name: 'Guidelines', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Review policy' })).toBeVisible()
  await expect(page.getByText(/Last updated:/)).toBeVisible()
})

test('project admin edits and saves rendered markdown guidelines', async ({ page }) => {
  await mockWorkspace(page)
  await page.goto(`/#/projects/${id}/settings`)
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('textbox', { name: 'Markdown guidelines' }).fill('## New guidance\n- **Verify** facts')
  await page.getByRole('button', { name: 'Save guidelines' }).click()
  await expect(page.getByRole('heading', { name: 'New guidance' })).toBeVisible()
  await expect(page.getByText('Verify', { exact: true })).toBeVisible()
  await expect(page.getByText('Guidelines saved.')).toBeVisible()
})

test('condensed guidelines banner appears at the top of the queue', async ({ page }) => {
  await mockWorkspace(page)
  await page.goto(`/#/projects/${id}/queue`)
  const banner = page.getByRole('complementary', { name: 'Project annotation guidelines' })
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('Review policy')
  await expect(banner.getByRole('button', { name: 'Show full guidelines' })).toBeVisible()
})
