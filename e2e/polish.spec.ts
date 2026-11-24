import { test, expect } from '@playwright/test'

test('global navigation and help stay inactive while typing', async ({ page }) => {
  await page.goto('/#/upload')
  await page.getByLabel('Label ID').fill('gq?')
  await expect(page).toHaveURL(/#\/upload$/)
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toHaveCount(0)
  await page.getByRole('heading', { name: 'Start with your labels.' }).click()
  await page.keyboard.press('?')
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.keyboard.press('g')
  await page.keyboard.press('q')
  await expect(page).toHaveURL(/#\/queue$/)
})

test('dark mode survives reload', async ({ page }) => {
  await page.goto('/#/upload')
  await page.getByRole('button', { name: 'Toggle dark mode' }).click()
  const selected = await page.evaluate(() => localStorage.getItem('dlj-theme'))
  expect(selected).toMatch(/^(dark|light)$/)
  await page.reload()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('dlj-theme'))).toBe(selected)
  expect(await page.locator('html').evaluate(element => element.classList.contains('dark')))
    .toBe(selected === 'dark')
})
