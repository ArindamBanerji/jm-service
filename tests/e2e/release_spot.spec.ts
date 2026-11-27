import { randomUUID } from 'node:crypto'
import { expect } from '@playwright/test'
import { api, download, open, project, seed, test, verify } from './release_fixture'

test.describe.configure({ timeout: 60_000 })

test('test_homepage_loads', async ({ page, server }) => {
  await page.goto(server.url)
  await expect(page).toHaveTitle('RGI Data Label Judgment')
  await expect(page.getByRole('heading', { name: 'Start with your labels.' })).toBeVisible()
})
test('test_login_and_project_list', async ({ page, browser, server }) => {
  const p = await project(page, server)
  const signedOut = await browser.newContext()
  try {
    const tab = await signedOut.newPage()
    await open(tab, server, 'upload')
    const credential = tab.getByLabel('API KEY', { exact: true })
    await expect(credential).toBeEmpty()
    await credential.fill(server.key)
    const loaded = tab.waitForResponse(r => new URL(r.url()).pathname === '/v1/projects' && r.ok())
    await credential.press('Enter')
    expect(await (await loaded).json()).toContainEqual(expect.objectContaining({ id: p.id, role: 'owner' }))
    await tab.getByRole('link', { name: 'Manage projects' }).click()
    await expect(tab.getByRole('link', { name: new RegExp(p.name) })).toBeVisible()
  } finally {
    await signedOut.close()
  }
})
test('test_create_text_project', async ({ page, server }) => {
  const alias = 'launch-' + randomUUID()
  const capabilities = page.waitForResponse(response => new URL(response.url()).pathname === '/v1/projects/capabilities')
  await open(page, server, 'projects')
  expect((await capabilities).status()).toBe(200)
  await page.getByLabel('Project name').fill(alias)
  await page.getByLabel('Public ID').fill(alias)
  await expect(page.getByLabel('Content type')).toHaveValue('text')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page).toHaveURL(/\/queue$/)
  await page.getByRole('link', { name: 'Manage projects' }).click()
  await expect(page.getByRole('link', { name: new RegExp(alias) })).toBeVisible()
})
test('test_labeling_queue_renders', async ({ page, server }) => {
  const { id } = await project(page, server)
  await seed(page, server, id, 2)
  const queue = page.waitForResponse(response => new URL(response.url()).pathname === `/v1/projects/${id}/labels/pending`)
  await open(page, server, 'projects/' + id + '/queue')
  expect((await queue).headers()['x-total-count']).toBe('2')
  await expect(page.getByRole('link', { name: 'Review →' })).toHaveCount(2)
})
test('test_score_and_verify', async ({ page, server }) => {
  const { id } = await project(page, server)
  await seed(page, server, id)
  await open(page, server, 'projects/' + id + '/review/release-0')
  await verify(page)
  expect((await api(page, server, '/' + id + '/labels/items/release-0')).verified_outcome).toBe(true)
})
test('test_analytics_panels_render', async ({ page, server }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
  const { id } = await project(page, server)
  await seed(page, server, id)
  await open(page, server, 'projects/' + id + '/dashboard')
  for (const name of ['Label Distribution', 'Throughput']) await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Analytics', exact: true }).click()
  for (const name of ['Confusion Matrix', 'Agreement']) await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  expect(errors).toEqual([])
})
test('test_export_download', async ({ page, server }) => {
  const { id } = await project(page, server)
  await seed(page, server, id)
  await open(page, server, 'projects/' + id + '/queue')
  const csv = await download(page)
  expect(csv.split('\n')[0]).toContain('current_label_id')
  expect(csv).toContain('Release sample 0')
})
test('test_guide_docs_render', async ({ page, server }) => {
  await open(page, server, 'docs')
  for (const name of ['Getting Started', 'Uploading Data', 'Scoring & Verification', 'Predictions', 'Export', 'Webhooks', 'Python Client', 'Billing']) {
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  }
})
