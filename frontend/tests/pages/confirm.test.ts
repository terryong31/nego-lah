import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import ConfirmPage from '~/pages/confirm.vue'

type StubUser = {
  id: string
  email: string
  app_metadata?: { provider?: string }
  amr?: Array<{ method: string, timestamp: number }> | string[]
}
const userRef = ref<StubUser | null>(null)
const routeStub = reactive<{ query: Record<string, string | undefined>, hash?: string }>({ query: {} })

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useRoute', () => () => routeStub)

// The real `initLanguage` PUTs to the backend. Unmocked it 401s, and useApi's
// interceptor then pushes /login — asynchronously, so the redirect lands in
// whichever test happens to be running when the rejection settles.
const { initLanguageMock } = vi.hoisted(() => ({ initLanguageMock: vi.fn() }))
mockNuxtImport('useLanguage', () => () => ({ initLanguage: initLanguageMock }))

function spyOnRouterPush(wrapper: { vm: { $router: { push: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'push').mockImplementation(() => Promise.resolve())
}

function spyOnRouterReplace(wrapper: { vm: { $router: { replace: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'replace').mockImplementation(() => Promise.resolve())
}

/**
 * Swaps in a partial `Location` so the page sees a real callback URL. Returns
 * the restore function — the real object has to come back before the next test.
 */
function stubLocation(pathname: string, search: string, hash = '', replace = vi.fn()) {
  const original = window.location
  // @ts-expect-error - reassigning location is allowed in the test DOM
  delete window.location
  // @ts-expect-error - a partial Location is enough for these assertions
  window.location = { ...original, pathname, search, hash, replace }
  return () => {
    // @ts-expect-error - restore the real Location object
    delete window.location
    // @ts-expect-error - restore the real Location object
    window.location = original
  }
}

describe('pages/confirm.vue', () => {
  let wrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

  beforeEach(() => {
    vi.useFakeTimers()
    initLanguageMock.mockReset().mockResolvedValue(undefined)
    userRef.value = null
    routeStub.query = {}
    routeStub.hash = ''
  })

  afterEach(() => {
    vi.useRealTimers()
    wrapper?.unmount()
    wrapper = undefined
  })

  it('renders a loading indicator and confirming message initially', async () => {
    wrapper = await mountSuspended(ConfirmPage)

    expect(wrapper.findComponent({ name: 'UProgress' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('Confirming your session, please wait...')
  })

  it('displays the Email Confirmed screen once the user ref becomes truthy', async () => {
    routeStub.query = { token_hash: 'tok', type: 'signup' }
    userRef.value = null
    wrapper = await mountSuspended(ConfirmPage)

    expect(wrapper.findComponent({ name: 'UProgress' }).exists()).toBe(true)

    userRef.value = { id: 'u1', email: 'user@example.com' }
    await flushPromises()

    expect(wrapper.text()).toContain('Email Confirmed!')
    expect(wrapper.text()).toContain('Your email has been successfully verified')
    const button = wrapper.findComponent({ name: 'UButton' })
    expect(button.exists()).toBe(true)
    expect(button.props('label')).toBe('Explore Storefront')
  })

  it('navigates to / when clicking Explore Storefront', async () => {
    routeStub.query = { token_hash: 'tok', type: 'signup' }
    userRef.value = { id: 'u1', email: 'user@example.com' }
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    await flushPromises()

    const button = wrapper.findComponent({ name: 'UButton' })
    await button.trigger('click')

    expect(pushSpy).toHaveBeenCalledWith('/')
  })

  it('navigates to redirect target when query has a safe redirect path', async () => {
    userRef.value = { id: 'u1', email: 'user@example.com' }
    routeStub.query = { redirect: '/items/item-1', token_hash: 'tok', type: 'signup' }
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    await flushPromises()

    const button = wrapper.findComponent({ name: 'UButton' })
    await button.trigger('click')

    expect(pushSpy).toHaveBeenCalledWith('/items/item-1')
  })

  it('auto-redirects to / after countdown expires', async () => {
    routeStub.query = { token_hash: 'tok', type: 'signup' }
    userRef.value = { id: 'u1', email: 'user@example.com' }
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    await flushPromises()
    expect(pushSpy).not.toHaveBeenCalled()

    vi.advanceTimersByTime(5000)
    await flushPromises()

    expect(pushSpy).toHaveBeenCalledWith('/')
  })

  it('displays the Verification Failed screen when error params are present', async () => {
    routeStub.query = {
      error: 'access_denied',
      error_code: 'otp_expired',
      error_description: 'Email link is invalid or has expired'
    }

    wrapper = await mountSuspended(ConfirmPage)

    expect(wrapper.text()).toContain('Verification Failed')
    expect(wrapper.text()).toContain('Email link is invalid or has expired')
    const button = wrapper.findComponent({ name: 'UButton' })
    expect(button.exists()).toBe(true)
    expect(button.props('label')).toBe('Back to Login')
  })

  // /confirm is the single Supabase auth callback route, so a Google sign-in
  // lands here too. It is NOT an email confirmation: showing "Email Confirmed!"
  // plus a countdown to someone who just clicked "Sign in with Google" is both
  // wrong and a pointless interstitial.
  describe('OAuth callback flow', () => {
    it('redirects straight to / without showing the Email Confirmed screen', async () => {
      routeStub.query = { flow: 'oauth' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com' }
      await flushPromises()

      expect(replaceSpy).toHaveBeenCalledWith('/')
      expect(wrapper.text()).not.toContain('Email Confirmed!')
    })

    it('redirects to the safe redirect target when one is carried through', async () => {
      routeStub.query = { flow: 'oauth', redirect: '/chat?item_id=item-1' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com' }
      await flushPromises()

      expect(replaceSpy).toHaveBeenCalledWith('/chat?item_id=item-1')
    })

    it('never renders the success screen when the session is already present at mount', async () => {
      routeStub.query = { flow: 'oauth' }
      userRef.value = { id: 'u1', email: 'user@example.com' }

      wrapper = await mountSuspended(ConfirmPage)
      await flushPromises()

      expect(wrapper.text()).not.toContain('Email Confirmed!')
      expect(wrapper.text()).not.toContain('Explore Storefront')
    })

    it('detects an untagged social callback from the session sign-in method', async () => {
      routeStub.query = { code: 'abc' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com', amr: [{ method: 'oauth', timestamp: 1 }] }
      await flushPromises()

      expect(replaceSpy).toHaveBeenCalledWith('/')
      expect(wrapper.text()).not.toContain('Email Confirmed!')
    })

    it('still shows the success screen for an email-provider confirmation', async () => {
      routeStub.query = { token_hash: 'tok', type: 'signup' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com', amr: [{ method: 'otp', timestamp: 1 }] }
      await flushPromises()

      expect(replaceSpy).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('Email Confirmed!')
    })

    // The account's original provider is NOT how the current session signed in.
    // An account created with a password and later linked to Google reports
    // `app_metadata.provider === 'email'` on every Google login, forever. `amr`
    // records what actually happened for THIS session.
    it('detects a Google login on an account that was originally email/password', async () => {
      routeStub.query = { code: 'abc' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = {
        id: 'u1',
        email: 'user@example.com',
        app_metadata: { provider: 'email' },
        amr: [{ method: 'oauth', timestamp: 1 }]
      }
      await flushPromises()

      expect(replaceSpy).toHaveBeenCalledWith('/')
      expect(wrapper.text()).not.toContain('Email Confirmed!')
    })

    it('reads the string form of amr as well as the object form', async () => {
      routeStub.query = { code: 'abc' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com', amr: ['oauth'] }
      await flushPromises()

      expect(replaceSpy).toHaveBeenCalledWith('/')
    })

    // Regression (SPEC-032): the visitor stayed on the spinner forever after a
    // Google login. `auth-redirect.global` reads `window.location` on the first
    // navigation, and the browser URL is still the spent `/confirm?code=...`
    // until the outgoing navigation commits — so the redirect away from here
    // was bounced straight back. Clearing the params first closes that window.
    it('clears the callback params from the URL before navigating away', async () => {
      routeStub.query = { flow: 'oauth', code: 'abc' }
      wrapper = await mountSuspended(ConfirmPage)

      const restore = stubLocation('/confirm', '?flow=oauth&code=abc')
      const replaceStateSpy = vi.spyOn(window.history, 'replaceState')
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com' }
      await flushPromises()

      expect(replaceStateSpy).toHaveBeenCalled()
      expect(replaceSpy).toHaveBeenCalledWith('/')
      expect(replaceStateSpy.mock.invocationCallOrder[0]!)
        .toBeLessThan(replaceSpy.mock.invocationCallOrder[0]!)

      restore()
    })

    // Belt and braces: if the router navigation is swallowed for any reason,
    // the callback page must not leave the visitor stranded on the spinner.
    it('falls back to a hard navigation when the router redirect is swallowed', async () => {
      routeStub.query = { flow: 'oauth', code: 'abc' }
      wrapper = await mountSuspended(ConfirmPage)

      const hardReplace = vi.fn()
      const restore = stubLocation('/confirm', '', '', hardReplace)
      spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com' }
      await flushPromises()
      expect(hardReplace).not.toHaveBeenCalled()

      vi.advanceTimersByTime(3000)
      await flushPromises()

      expect(hardReplace).toHaveBeenCalledWith('/')

      restore()
    })

    it('does not start the countdown on the OAuth path', async () => {
      routeStub.query = { flow: 'oauth' }
      wrapper = await mountSuspended(ConfirmPage)
      const pushSpy = spyOnRouterPush(wrapper)
      spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com' }
      await flushPromises()

      vi.advanceTimersByTime(6000)
      await flushPromises()

      expect(pushSpy).not.toHaveBeenCalled()
    })
  })

  // Landing on /confirm with a session but no confirmation params at all means
  // nothing was confirmed — the visitor just navigated to the callback route.
  // Announcing "Email Confirmed!" there is simply untrue.
  describe('stray navigation to /confirm', () => {
    it('redirects away instead of claiming a confirmation happened', async () => {
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com', amr: [{ method: 'password', timestamp: 1 }] }
      await flushPromises()

      expect(wrapper.text()).not.toContain('Email Confirmed!')
      expect(replaceSpy).toHaveBeenCalledWith('/')
    })

    it('honours the redirect target on a stray visit', async () => {
      routeStub.query = { redirect: '/orders' }
      wrapper = await mountSuspended(ConfirmPage)
      const replaceSpy = spyOnRouterReplace(wrapper)

      userRef.value = { id: 'u1', email: 'user@example.com' }
      await flushPromises()

      expect(replaceSpy).toHaveBeenCalledWith('/orders')
    })
  })

  it('points Back to Login button to loginRedirect with redirect query when present', async () => {
    routeStub.query = {
      error: 'access_denied',
      error_code: 'otp_expired',
      redirect: '/chat?item_id=item-1'
    }

    wrapper = await mountSuspended(ConfirmPage)

    const empty = wrapper.findComponent({ name: 'UEmpty' })
    expect(empty.props('actions')).toEqual([
      expect.objectContaining({
        label: 'Back to Login',
        to: { path: '/login', query: { redirect: '/chat?item_id=item-1' } }
      })
    ])
  })
})
