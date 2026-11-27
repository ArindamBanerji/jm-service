import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createInterface } from 'node:readline'
import { randomUUID } from 'node:crypto'
import { expect, test as base, type Page } from '@playwright/test'

type Server = { url: string; key: string }
const test = base.extend<{}, { server: Server }>({
  server: [async ({}, use) => {
    const child = spawn('python', ['-u', '-m', 'tests.sprint0_browser_server'], {
      stdio: ['pipe', 'pipe', 'inherit'],
      env: { ...process.env, DLJ_IMAGE_PROJECTS_ENABLED: 'true' },
    })
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
test.setTimeout(60_000)

const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64')

test.beforeEach(async ({ page, server }) => {
  await page.addInitScript(key => localStorage.setItem('rgi-api-key', key), server.key)
})

async function api(page: Page, server: Server, path: string, data?: unknown) {
  const response = await page.request.fetch(`${server.url}/v1/projects${path}`, {
    method: data === undefined ? 'GET' : 'POST', headers: { 'X-Api-Key': server.key }, data,
  })
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy()
  return response
}

async function imageProject(page: Page, server: Server, prefix = 'image') {
  const alias = `${prefix}-${randomUUID()}`
  return (await (await api(page, server, '', {
    name: `Image ${alias}`, public_domain_id: alias, categories: ['A', 'B'],
    factors: ['quality', 'difficulty'], actions: ['approve', 'reject'],
    content_type: 'image', label_schema: 'single',
  })).json()) as { id: string; public_domain_id: string }
}

async function uploadImages(page: Page, server: Server, project: { id: string; public_domain_id: string }, count = 1, broken = false) {
  const items = Array.from({ length: count }, (_, index) => ({
    label_id: `image-${index + 1}`, category: index % 2 ? 'B' : 'A',
    text: `Bird caption ${index + 1}`, factors: { quality: .9 - index * .05, difficulty: .15 + index * .05 },
    content: { content_type: 'image_classification', spans: [], tags: [],
      image_url: broken ? 'https://images.example.test/broken.png' : `https://images.example.test/bird-${index + 1}.png` },
  }))
  await api(page, server, `/${project.id}/labels/batch`, { request_key: randomUUID(), items })
}

async function open(page: Page, server: Server, route: string) {
  await page.goto(`${server.url}/#/${route}`)
}

async function loadExternalImage(page: Page) {
  const consent = page.getByRole('button', { name: 'Load external image' })
  await expect(consent).toBeVisible({ timeout: 30_000 })
  await consent.click()
}

test('test_image_project_creation', async ({ page, server }) => {
  await open(page, server, 'projects')
  await expect(page.getByLabel('Content type')).toBeVisible()
  await page.getByLabel('Project name').fill('Bird Review')
  await page.getByLabel('Public ID').fill(`birds-${randomUUID()}`)
  await page.getByLabel('Content type').selectOption('image')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page).toHaveURL(/\/queue$/)
  await page.getByRole('link', { name: 'Manage projects' }).click()
  await expect(page.getByRole('link', { name: /Bird Review/ })).toContainText('Image')
})

test('test_text_project_creation_unchanged', async ({ page, server }) => {
  const capabilities = page.waitForResponse(r => r.url().endsWith('/v1/projects/capabilities'))
  await open(page, server, 'projects')
  expect((await capabilities).ok()).toBeTruthy()
  await expect(page.getByLabel('Content type')).toHaveValue('text')
  await expect(page.getByLabel('Label schema')).toHaveValue('single')
  await expect(page.getByText('Choose what reviewers will label. This locks after the first item.')).toBeVisible()
})

test('an image import rejects missing numeric evidence before scoring', async ({ page, server }) => {
  const project = await imageProject(page, server)
  await open(page, server, `projects/${project.id}/upload`)
  await page.locator('input[type=file]').setInputFiles({
    name: 'rows.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify([{
      label_id: 'invalid-factor', category: 'A', factors: { quality: null, difficulty: .2 },
      item_media_url: 'https://images.example.test/frame.png',
    }])),
  })
  await expect(page.getByRole('alert')).toContainText('quality must be between 0 and 1')
  const result = await api(page, server, `/${project.id}/next-batch`)
  expect((await result.json()).total_pending).toBe(0)
})

test('existing projects are available when capabilities cannot load', async ({ page, server }) => {
  await imageProject(page, server, 'earlier')
  const project = await imageProject(page, server)
  let followedPage = false
  await page.route(/\/v1\/projects(?:\?.*)?$/, async route => {
    const url = new URL(route.request().url())
    if (url.searchParams.has('offset')) followedPage = true
    url.searchParams.set('limit', '1')
    await route.continue({ url: url.toString() })
  })
  await page.route('**/v1/projects/capabilities', route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  const lastPage = page.waitForResponse(async response => new URL(response.url()).pathname === '/v1/projects' &&
    response.ok() && await response.headerValue('X-Next-Offset') === null)
  await open(page, server, 'projects')
  await lastPage
  await expect(page.getByRole('link', { name: new RegExp(project.public_domain_id) })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Project creation options')
  await expect(page.getByLabel('Content type')).toHaveCount(0)
  expect(followedPage).toBe(true)
})

test('test_image_in_queue', async ({ page, server }) => {
  const project = await imageProject(page, server); await uploadImages(page, server, project)
  await page.route('https://images.example.test/bird-1.png', route => route.fulfill({ contentType: 'image/png', body: pixel }))
  const queue = page.waitForResponse(response => {
    const url = new URL(response.url())
    const root = `/v1/projects/${project.id}`
    return url.pathname === root + '/labels/pending' ||
      (url.pathname === root + '/next-batch' && url.searchParams.get('n') === '50')
  })
  await open(page, server, `projects/${project.id}/queue`)
  expect((await queue).ok()).toBeTruthy()
  await expect(page.getByText('Image', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole('link', { name: 'Review →' }).click()
  await loadExternalImage(page)
  await expect(page.getByRole('img', { name: 'Bird caption 1' })).toBeVisible()
})

test('test_image_broken_fallback', async ({ page, server }) => {
  const project = await imageProject(page, server); await uploadImages(page, server, project, 1, true)
  await page.route('https://images.example.test/broken.png', route => route.fulfill({ status: 404, body: '' }))
  await open(page, server, `projects/${project.id}/review/image-1`)
  await loadExternalImage(page)
  await expect(page.getByRole('alert').filter({ hasText: 'Image not available' })).toContainText('images.example.test')
  await page.getByLabel('Choose category').selectOption('B')
  await expect(page.getByRole('button', { name: 'Relabel' })).toBeEnabled()
})

test('test_image_label_and_score', async ({ page, server }) => {
  const project = await imageProject(page, server); await uploadImages(page, server, project)
  await open(page, server, `projects/${project.id}/review/image-1`)
  await expect(page.getByText('Factor signals', { exact: true })).toBeVisible()
  await expect(page.locator('.factor')).toHaveCount(2)
  await expect(page.getByLabel('Choose category')).toHaveValue('A')
  await expect(page.getByRole('heading', { name: 'approve' })).toBeVisible()
})

test('test_image_keyboard_verify', async ({ page, server }) => {
  const project = await imageProject(page, server); await uploadImages(page, server, project, 2)
  await open(page, server, `projects/${project.id}/review/image-1`)
  await page.getByLabel('Known outcome').selectOption('correct')
  await page.locator('h1').click()
  const verified = page.waitForResponse(response => response.url().endsWith('/labels/verify') && response.status() === 200)
  await page.keyboard.press('a')
  await verified
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/review/image-2$`))
})

test('test_image_project_settings_locked', async ({ page, server }) => {
  const project = await imageProject(page, server); await uploadImages(page, server, project)
  await open(page, server, `projects/${project.id}/settings`)
  await expect(page.getByText('Content type:')).toBeVisible()
  await expect(page.getByText('Locked after first item')).toBeVisible()
  await expect(page.getByLabel('Content type')).toHaveCount(0)
})

test('test_image_csv_import', async ({ page, server }) => {
  const project = await imageProject(page, server)
  await open(page, server, `projects/${project.id}/upload`)
  await page.locator('input[type=file]').setInputFiles({
    name: 'images.csv', mimeType: 'text/csv', buffer: Buffer.from(
      'label_id,category,item_text,item_media_url,factor_quality,factor_difficulty\ncsv-image,A,CSV bird,https://images.example.test/csv.png,0.9,0.1'),
  })
  await expect(page.getByLabel('Image import preview')).toContainText('CSV bird')
  await expect(page.getByLabel('Image import preview')).toContainText('Image URL')
  await page.getByRole('button', { name: 'Import image labels' }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/queue$`))
  await page.getByRole('link', { name: 'Review →' }).click()
  await expect(page.getByText('CSV bird')).toBeVisible()
})

test('test_mobile_image_queue', async ({ page, server }) => {
  const project = await imageProject(page, server); await uploadImages(page, server, project)
  await page.setViewportSize({ width: 400, height: 800 })
  await page.route('https://images.example.test/bird-1.png', route => route.fulfill({ contentType: 'image/png', body: pixel }))
  await open(page, server, `projects/${project.id}/review/image-1`)
  await loadExternalImage(page)
  await expect(page.getByRole('img', { name: 'Bird caption 1' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve recommendation (A)' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
