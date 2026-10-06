import { expect, test } from '@playwright/test'
import { API, EMAIL, PASSWORD } from './env'

// Needs a confirmed buyer account in the target environment. Never point this
// at production with a real customer's credentials.
test.skip(!EMAIL || !PASSWORD, 'set E2E_EMAIL and E2E_PASSWORD to run session tests')

test('sign-in sets an httpOnly session the page cannot read, and logout ends it', async ({ page, context }) => {
  await page.goto('/login')
  await page.locator('input[type="email"]').fill(EMAIL!)
  await page.locator('input[type="password"]').fill(PASSWORD!)
  await page.locator('form button[type="submit"]').click()
  await expect(page).not.toHaveURL(/\/login/)

  const sid = (await context.cookies(API)).find(c => c.name === 'nl_sid')
  expect(sid, 'nl_sid cookie set on the API origin').toBeTruthy()
  expect(sid!.httpOnly).toBe(true)
  expect(await page.evaluate(() => document.cookie)).not.toContain('nl_sid')

  const session = await page.request.get(`${API}/auth/session`)
  expect(session.status()).toBe(200)

  const csrf = (await context.cookies(API)).find(c => c.name === 'nl_csrf')?.value ?? ''
  const out = await page.request.post(`${API}/auth/logout`, { headers: { 'X-CSRF-Token': csrf } })
  expect(out.ok()).toBeTruthy()
  expect((await page.request.get(`${API}/auth/session`)).status()).toBe(401)
})
