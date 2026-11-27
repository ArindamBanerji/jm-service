import { expect, test, type Page, type Route } from '@playwright/test'

const project = { id: '77777777-7777-4777-8777-777777777777', public_domain_id: 'analytics-demo', name: 'Analytics Demo', status: 'active', settings_version: 1, role: 'owner' }
const distribution = { categories: [
  { name: 'Technology', count: 80, pct: 80, verified: 40, pending: 40 },
  { name: 'Science', count: 1, pct: 1, verified: 0, pending: 1 },
], total: 100, imbalance_warning: 'Science has 1.0% of labels — consider adding more examples' }
const throughput = { daily: [
  { date: '2026-11-24', labels: 8, verified: 5, avg_time_sec: 14 },
  { date: '2026-11-25', labels: 12, verified: 9, avg_time_sec: 12 },
  { date: '2026-11-26', labels: 18, verified: 11, avg_time_sec: 13 },
], annotators: [{ id: 'jchen', name: 'jchen', labels_total: 38, labels_today: 18, avg_time_sec: 13 }], summary: { total_labels: 38, avg_per_day: 12.7, avg_time_sec: 13 } }
const agreement = { annotators: ['jchen', 'mlee'], matrix: [[1, .87], [.87, 1]], per_category: { Technology: [[1, .94], [.94, 1]], Sports: [[1, .72], [.72, 1]] }, lowest_pair: { a: 'jchen', b: 'mlee', agreement: .87, worst_category: 'Sports' }, note: null }

async function identity(page: Page) {
  await page.addInitScript(() => localStorage.setItem('rgi-api-key', 'analytics-key'))
}

async function projectBase(route: Route) {
  const request = route.request(), url = new URL(request.url()), path = url.pathname
  if (path === '/v1/projects' && request.method() === 'GET') { await route.fulfill({ json: [project] }); return true }
  if (path.endsWith('/dashboard/overview')) { await route.fulfill({ json: { domain_id: 'analytics-demo', overall_accuracy: .91, total_verified: 81, total_labels: 100, categories: [], inversion: null, compounding_curve: [], generated_at: '2026-11-26T00:00:00Z' } }); return true }
  if (path.endsWith('/dashboard/corrections')) { await route.fulfill({ json: { domain_id: 'analytics-demo', total_corrections: 0, correction_rate: null, patterns: [], top_pattern: null } }); return true }
  if (path.endsWith('/dashboard/compounding')) { await route.fulfill({ json: { domain_id: 'analytics-demo', category: null, points: [], baseline_accuracy: .8, current_accuracy: .91, improvement: 11 } }); return true }
  if (path.endsWith('/dashboard/iaa')) { await route.fulfill({ json: { pairs: [], overall_kappa: null, total_overlapping_labels: 0 } }); return true }
  if (path.endsWith('/sla')) { await route.fulfill({ json: { floor_pct: 71.2, current_accuracy: 91.2, margin: 20, gate_status: 'safe', auto_approve_active: true, verified_count: 81, min_verified_for_sla: 50 } }); return true }
  return false
}

async function dashboard(page: Page, data = distribution) {
  await identity(page)
  await page.route('**/v1/**', async route => {
    if (await projectBase(route)) return
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/analytics/distribution')) return route.fulfill({ json: data })
    if (path.endsWith('/analytics/throughput')) return route.fulfill({ json: throughput })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  await page.goto(`/#/projects/${project.id}/dashboard`)
}

async function analytics(page: Page) {
  await identity(page)
  await page.route('**/v1/**', async route => {
    if (await projectBase(route)) return
    const url = new URL(route.request().url()), path = url.pathname
    if (path.endsWith('/analytics/confusion')) {
      const prediction = url.searchParams.get('source') === 'prediction'
      return route.fulfill({ json: { categories: ['Technology', 'Business'], matrix: prediction ? [[2, 4], [0, 3]] : [[8, 1], [2, 7]], top_confusions: prediction ? [{ from: 'Technology', to: 'Business', count: 4, pct: 66.7 }] : [{ from: 'Business', to: 'Technology', count: 2, pct: 22.2 }] } })
    }
    if (path.endsWith('/analytics/agreement')) return route.fulfill({ json: agreement })
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } })
  })
  await page.goto(`/#/projects/${project.id}/analytics`)
}

test('distribution chart renders on dashboard', async ({ page }) => {
  await dashboard(page)
  await expect(page.getByRole('heading', { name: 'Label Distribution' })).toBeVisible()
  await expect(page.getByTestId('distribution-chart').getByText('Technology')).toBeVisible()
  await expect(page.getByRole('img', { name: /Technology: 80 labels/ })).toBeVisible()
})

test('distribution imbalance alert is visible', async ({ page }) => {
  await dashboard(page)
  await expect(page.getByRole('alert').filter({ hasText: 'Science has 1.0%' })).toBeVisible()
})

test('throughput chart renders with data points', async ({ page }) => {
  await dashboard(page)
  await expect(page.getByRole('heading', { name: 'Throughput' })).toBeVisible()
  await expect(page.getByText('12.7 labels/day average')).toBeVisible()
  await expect(page.getByTestId('throughput-chart').locator('.recharts-line-dot')).toHaveCount(6)
})

test('confusion matrix renders colored cells', async ({ page }) => {
  await analytics(page)
  await expect(page.getByTestId('confusion-matrix')).toBeVisible()
  await expect(page.getByTitle(/8 Technology items were labeled as Technology/)).toBeVisible()
  await expect(page.getByText('Top confusion pairs')).toBeVisible()
})

test('confusion source filter changes the matrix', async ({ page }) => {
  await analytics(page)
  await expect(page.getByTitle(/8 Technology items were labeled as Technology/)).toBeVisible()
  await page.getByRole('button', { name: 'Prediction' }).click()
  await expect(page.getByTitle(/2 Technology items were labeled as Technology/)).toBeVisible()
  await expect(page.getByText('Technology → Business')).toBeVisible()
})

test('agreement heatmap renders annotator names', async ({ page }) => {
  await analytics(page)
  await expect(page.getByTestId('agreement-heatmap')).toBeVisible()
  await expect(page.getByTitle('jchen and mlee agree 87% overall')).toBeVisible()
  await expect(page.getByText(/Lowest agreement:.*jchen.*mlee.*87%/)).toBeVisible()
})

test('analytics panels remain usable at 400px width', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 900 })
  await analytics(page)
  await expect(page.getByRole('heading', { name: 'Confusion Matrix' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Agreement' })).toBeVisible()
  const viewport = page.locator('.main')
  await expect(viewport).toBeVisible()
  expect(await viewport.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBeTruthy()
})
