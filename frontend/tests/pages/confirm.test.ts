/**
 * SPEC-093 — /confirm is a landing screen, not an auth step.
 *
 * This page used to perform the exchange itself: read `?code=` / `#access_token=`
 * out of three places in the URL, call `exchangeCodeForSession` or `verifyOtp`,
 * wait for a session to appear, work out whether this was OAuth or an email
 * confirmation, and scrub the credential back out of the address bar. All of it
 * now happens on the backend, which redeems the link and 302s here with a
 * session cookie and nothing but `?status=`.
 *
 * So what is left to test is small: it shows the outcome, and it forwards a link
 * that was already in someone's inbox when this shipped.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import ConfirmPage from '~/pages/confirm.vue'
import { makeAuthStub } from '../helpers/auth'

const userRef = ref<{ id: string } | null>(null)
const authStub = makeAuthStub(userRef)
const routeStub = reactive<{ query: Record<string, string | undefined> }>({ query: {} })

mockNuxtImport('useAuth', () => () => authStub)
mockNuxtImport('useRoute', () => () => routeStub)

/**
 * Swaps in a partial `Location` so the page can be watched navigating away.
 * Returns the restore function — the real object has to come back before the
 * next test.
 */
function stubLocation(replace = vi.fn()) {
  const original = window.location
  // @ts-expect-error - reassigning location is allowed in the test DOM
  delete window.location
  // @ts-expect-error - a partial Location is enough for these assertions
  window.location = { ...original, replace }
  return { replace, restore: () => {
    // @ts-expect-error - restore the real Location object
    delete window.location
    // @ts-expect-error - restore the real Location object
    window.location = original
  } }
}

describe('pages/confirm.vue', () => {
  let wrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined
  let location: ReturnType<typeof stubLocation> | undefined

  beforeEach(() => {
    userRef.value = null
    routeStub.query = {}
    authStub.fetchSession.mockReset().mockImplementation(async () => {
      userRef.value = { id: 'user-1' }
      return userRef.value
    })
  })

  afterEach(() => {
    location?.restore()
    location = undefined
    wrapper?.unmount()
    wrapper = undefined
  })

  it('reads the session the redirect established and shows the confirmation', async () => {
    wrapper = await mountSuspended(ConfirmPage)
    await flushPromises()

    // The cookie was set on the 302 that brought the browser here, so this is
    // the first chance to learn who it belongs to.
    expect(authStub.fetchSession).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Email Confirmed')
  })

  it('offers a way on to the storefront', async () => {
    wrapper = await mountSuspended(ConfirmPage)
    await flushPromises()

    const link = wrapper.findAll('a').find(a => a.attributes('href') === '/')
    expect(link).toBeTruthy()
  })

  it('honours a safe redirect target', async () => {
    routeStub.query = { redirect: '/orders' }
    wrapper = await mountSuspended(ConfirmPage)
    await flushPromises()

    const link = wrapper.findAll('a').find(a => a.attributes('href') === '/orders')
    expect(link).toBeTruthy()
  })

  it('refuses an offsite redirect target', async () => {
    routeStub.query = { redirect: '//evil.com/steal' }
    wrapper = await mountSuspended(ConfirmPage)
    await flushPromises()

    expect(wrapper.html()).not.toContain('evil.com')
  })

  it('shows the failure screen when the backend rejected the link', async () => {
    routeStub.query = { error: 'link_invalid' }
    wrapper = await mountSuspended(ConfirmPage)
    await flushPromises()

    expect(wrapper.text()).toContain('Verification Failed')
    expect(wrapper.text()).toContain('Email link is invalid or has expired')
    // Nothing to read: the redirect that failed set no cookie.
    expect(authStub.fetchSession).not.toHaveBeenCalled()
  })

  describe('links that were already in an inbox', () => {
    it('forwards a legacy ?code= to the API callback, which owns the exchange now', async () => {
      location = stubLocation()
      routeStub.query = { code: 'legacy-code' }

      wrapper = await mountSuspended(ConfirmPage)
      await flushPromises()

      expect(location.replace).toHaveBeenCalledTimes(1)
      const forwarded = new URL(location.replace.mock.calls[0]![0] as string)
      expect(forwarded.pathname).toBe('/auth/callback')
      expect(forwarded.searchParams.get('code')).toBe('legacy-code')
      // It must not try to confirm anything itself on the way past.
      expect(authStub.fetchSession).not.toHaveBeenCalled()
    })

    it('forwards a legacy ?token_hash= with its type intact', async () => {
      location = stubLocation()
      routeStub.query = { token_hash: 'legacy-hash', type: 'recovery' }

      wrapper = await mountSuspended(ConfirmPage)
      await flushPromises()

      const forwarded = new URL(location.replace.mock.calls[0]![0] as string)
      expect(forwarded.searchParams.get('token_hash')).toBe('legacy-hash')
      expect(forwarded.searchParams.get('type')).toBe('recovery')
    })
  })
})
