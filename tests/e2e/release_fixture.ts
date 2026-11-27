import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createInterface } from 'node:readline'
import { expect, test as base, type Page } from '@playwright/test'

type Server = { url: string; key: string }
export const test = base.extend<{}, { server: Server }>({
  server: [async ({}, use) => {
    const child = spawn('python', ['-u', '-m', 'tests.release_server'], {
      stdio: ['pipe', 'pipe', 'inherit'],
      env: { ...process.env, DLJ_IMAGE_PROJECTS_ENABLED: 'true', DLJ_INLINE_IMAGES_ENABLED: 'true' },
    })
    const lines = createInterface({ input: child.stdout })
    const exited = once(child, 'exit')
    try {
      const [line] = await Promise.race([once(lines, 'line'), exited.then(() => { throw Error('Service exited during startup') })])
      const server: Server = JSON.parse(line)
      await use(server)
    } finally {
      child.stdin.end()
      const [code] = await exited
      lines.close()
      expect(code).toBe(0)
    }
  }, { scope: 'worker', timeout: 120_000 }],
  page: async ({ page, server }, use) => {
    await expect.poll(async () => {
      const health = await page.request.get(server.url + '/v1/health')
      return (await health.json()).status
    }, { message: 'Disposable service and both stores must become ready', timeout: 15_000 }).toBe('healthy')
    await page.addInitScript(key => localStorage.setItem('rgi-api-key', key), server.key)
    await use(page)
  },
})
export async function api(page: Page, server: Server, path: string, data?: unknown) {
  const response = await page.request.fetch(server.url + '/v1/projects' + path, {
    method: data === undefined ? 'GET' : 'POST', headers: { 'X-Api-Key': server.key }, data,
  })
  expect(response.ok(), path + ' ' + response.status()).toBeTruthy()
  return response.json()
}
export async function project(page: Page, server: Server, kind = 'text') {
  const name = 'release-' + randomUUID()
  return await api(page, server, '', { name, public_domain_id: name, content_type: kind, label_schema: 'single',
    categories: ['A', 'B'], actions: ['approve', 'reject'], factors: ['quality', 'difficulty'] }) as { id: string; name: string }
}
export async function seed(page: Page, server: Server, id: string, count = 1) {
  const items = Array.from({ length: count }, (_, i) => ({ label_id: 'release-' + i, text: 'Release sample ' + i,
    category: 'A', factors: { quality: .8, difficulty: .2 } }))
  const result = await api(page, server, '/' + id + '/labels/batch', { request_key: randomUUID(), items })
  expect(result.batch_size).toBe(count)
}
export async function open(page: Page, server: Server, path: string) {
  await page.goto(server.url + '/#/' + path)
}
export async function verify(page: Page) {
  await expect(page.getByText('Factor signals', { exact: true })).toBeVisible()
  await page.getByLabel('Known outcome').selectOption('correct')
  const response = page.waitForResponse(r => r.url().endsWith('/labels/verify'))
  await page.getByRole('button', { name: /Approve recommendation/ }).click()
  expect((await response).status()).toBe(200)
}
export async function download(page: Page) {
  const pending = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download project CSV' }).click()
  const completed = await pending
  expect(await completed.failure()).toBeNull()
  return readFile((await completed.path())!, 'utf8')
}
