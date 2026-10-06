import { expect, test } from '@playwright/test'
import { API } from './env'

// Anonymous and read-only: nothing here signs in, writes, or pays.

test.describe('API contract (SPEC-093/094)', () => {
  test('no session is a 401, not a crash or an empty 200', async ({ request }) => {
    const res = await request.get(`${API}/auth/session`)
    expect(res.status()).toBe(401)
  })

  test('Google sign-in returns to the API callback, not the SPA', async ({ request }) => {
    const res = await request.get(`${API}/auth/oauth/start`, { maxRedirects: 0 })
    expect(res.status()).toBe(302)
    const location = new URL(res.headers()['location'] ?? '')
    expect(location.pathname).toBe('/auth/v1/authorize')
    expect(location.searchParams.get('provider')).toBe('google')
    expect(location.searchParams.get('redirect_to')).toBe(`${API}/auth/callback`)
  })

  test('the retired SSE ticket route is gone', async ({ request }) => {
    const res = await request.post(`${API}/chat/notifications/ticket`)
    expect(res.status()).toBe(404)
  })

  test('a mutation without a session is refused', async ({ request }) => {
    const res = await request.post(`${API}/chat/read`, { data: {} })
    expect([401, 403]).toContain(res.status())
  })

  test('the notification stream refuses an anonymous client', async ({ request }) => {
    const res = await request.get(`${API}/chat/notifications/stream`, { timeout: 10_000 })
    expect([401, 403]).toContain(res.status())
  })
})

test.describe('the floor price never leaves the server (ADR-0009)', () => {
  test('public listings carry no min_price or buyer_id', async ({ request }) => {
    const res = await request.get(`${API}/items`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    const items: Record<string, unknown>[] = Array.isArray(body) ? body : body.items
    for (const item of items) {
      expect(item).not.toHaveProperty('min_price')
      expect(item).not.toHaveProperty('buyer_id')
    }
  })
})

test.describe('storefront', () => {
  test('loads and holds no credential in script-readable storage', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('#__nuxt')).toBeVisible()
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))
    expect(stored).not.toMatch(/access_token|refresh_token|sb-[a-z0-9]+-auth-token/i)
  })

  test('negotiating while signed out goes to login and comes back', async ({ page, request }) => {
    const body = await (await request.get(`${API}/items`)).json()
    const items: { item_id?: string, id?: string, status?: string }[] = Array.isArray(body) ? body : body.items
    const item = items.find(i => i.status === 'available') ?? items[0]
    test.skip(!item, 'no listings in this environment')

    await page.goto(`/items/${item!.item_id ?? item!.id}`)
    await page.locator('[data-tour="item-negotiate"]').click()
    await expect(page).toHaveURL(/\/login\?redirect=/)
    expect(decodeURIComponent(page.url())).toContain('/chat?item_id=')
  })
})
