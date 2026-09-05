import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import LoginPage from '~/pages/login.vue'

const { signInWithPasswordMock, signInWithOAuthMock } = vi.hoisted(() => ({
  signInWithPasswordMock: vi.fn(),
  signInWithOAuthMock: vi.fn()
}))

const { callMock } = vi.hoisted(() => ({
  callMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    signInWithPassword: signInWithPasswordMock,
    signInWithOAuth: signInWithOAuthMock
  }
}))

mockNuxtImport('useApi', () => () => ({
  call: callMock
}))

mockNuxtImport('useToast', () => () => ({
  add: toastAddMock
}))

// The @nuxtjs/supabase guard redirects before our own `auth` middleware can
// attach `?redirect=`, so it stashes the blocked page in a cookie instead
// (`saveRedirectToCookie` in nuxt.config). `pluck()` reads-and-clears it.
const { pluckMock } = vi.hoisted(() => ({ pluckMock: vi.fn() }))
mockNuxtImport('useSupabaseCookieRedirect', () => () => ({
  path: { value: null },
  pluck: pluckMock
}))

// Note: useRouter is deliberately left un-mocked (see tests/pages/items/index.test.ts
// for precedent). A partial stub like `{ push: vi.fn() }` breaks Nuxt's own internal
// client plugins (chunk-reload, navigation-repaint, ...) which call real router
// methods (`router.beforeEach`/`afterEach`/`beforeResolve`) during app init. Instead
// we spy on the real router's `push` method per-test via `wrapper.vm.$router`.
function spyOnRouterPush(wrapper: { vm: { $router: { push: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'push').mockImplementation(() => Promise.resolve())
}

async function fillAndSubmit(wrapper: Awaited<ReturnType<typeof mountSuspended>>, email = 'user@example.com', password = 'password123') {
  await wrapper.find('input[type="email"]').setValue(email)
  await wrapper.find('input[type="password"]').setValue(password)
  await wrapper.find('form').trigger('submit')
  // let the async onSubmit handler (multiple chained awaits) settle
  await flushPromises()
}

describe('pages/login.vue', () => {
  beforeEach(() => {
    signInWithPasswordMock.mockReset().mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null })
    signInWithOAuthMock.mockReset().mockResolvedValue({ error: null })
    callMock.mockReset().mockResolvedValue({ ok: true })
    toastAddMock.mockReset()
    pluckMock.mockReset().mockReturnValue(null)
  })

  it('renders the login form fields, Google provider, and footer links', async () => {
    const wrapper = await mountSuspended(LoginPage)

    expect(wrapper.text()).toContain('Login')
    expect(wrapper.text()).toContain('Enter your credentials to access your account.')
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Google')
    expect(wrapper.text()).toContain('Forgot password?')
    expect(wrapper.find('a[href="/forgot-password"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Don\'t have an account?')
    expect(wrapper.find('a[href="/register"]').exists()).toBe(true)
  })

  it('does not attempt login when the schema validation fails', async () => {
    const wrapper = await mountSuspended(LoginPage)

    await fillAndSubmit(wrapper, 'not-an-email', 'short')

    expect(signInWithPasswordMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Invalid email')
    expect(wrapper.text()).toContain('Must be at least 8 characters')
  })

  describe('successful password login', () => {
    it('signs in, probes the banned-account endpoint with the new user id, shows a success toast, and redirects home', async () => {
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(signInWithPasswordMock).toHaveBeenCalledWith({ email: 'user@example.com', password: 'password123' })
      expect(callMock).toHaveBeenCalledWith('/user/user-1/account')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Welcome back!',
        description: 'You have logged in successfully.',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith('/')
    })

    it('falls back to the supabase redirect cookie when the route carries no redirect query', async () => {
      pluckMock.mockReturnValue('/chat?item_id=item-9')
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(pushSpy).toHaveBeenCalledWith('/chat?item_id=item-9')
    })

    it('ignores an unsafe cookie value and goes home instead', async () => {
      pluckMock.mockReturnValue('//evil.com/chat')
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(pushSpy).toHaveBeenCalledWith('/')
    })

    it('prefers an explicit ?redirect= query over the cookie', async () => {
      pluckMock.mockReturnValue('/orders')
      const wrapper = await mountSuspended(LoginPage, {
        route: '/login?redirect=%2Fitems%2Fitem-1'
      })
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(pushSpy).toHaveBeenCalledWith('/items/item-1')
    })

    it('signs in and redirects to the safe redirect target when present in route query', async () => {
      const wrapper = await mountSuspended(LoginPage, {
        route: '/login?redirect=%2Fitems%2Fitem-1'
      })
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(pushSpy).toHaveBeenCalledWith('/items/item-1')
    })
  })

  describe('banned-account probe', () => {
    it('swallows a 403 "banned" probe error locally without a second error toast, success toast, or redirect', async () => {
      callMock.mockReset().mockRejectedValue({
        statusCode: 403,
        data: { detail: 'Your account has been banned' }
      })
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(signInWithPasswordMock).toHaveBeenCalledTimes(1)
      expect(callMock).toHaveBeenCalledTimes(1)
      // No toast at all: the useApi call itself already handled sign-out/redirect/toast
      // internally (per the source comment) — login.vue must not pile on a second one.
      expect(toastAddMock).not.toHaveBeenCalled()
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('matches the banned status via the alternate "status" field, case-insensitively', async () => {
      callMock.mockReset().mockRejectedValue({
        status: 403,
        data: { detail: 'ACCOUNT BANNED' }
      })
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).not.toHaveBeenCalled()
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('does not block a valid login on a transient (non-banned) probe error', async () => {
      callMock.mockReset().mockRejectedValue({ statusCode: 500, data: { detail: 'server error' } })
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      // Probe failure that isn't the banned-403 case is swallowed too, but login proceeds.
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Welcome back!',
        description: 'You have logged in successfully.',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith('/')
    })

    it('does not block a valid login on a 403 whose detail does not mention "banned"', async () => {
      callMock.mockReset().mockRejectedValue({ statusCode: 403, data: { detail: 'forbidden: insufficient scope' } })
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Welcome back!' }))
      expect(pushSpy).toHaveBeenCalledWith('/')
    })
  })

  describe('password login failure', () => {
    it('shows a "Login failed" toast with the Supabase error message and does not redirect', async () => {
      signInWithPasswordMock.mockResolvedValue({ data: { user: null }, error: new Error('Invalid login credentials') })
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Login failed',
        description: 'Invalid login credentials',
        color: 'error'
      })
      expect(callMock).not.toHaveBeenCalled()
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      signInWithPasswordMock.mockRejectedValue('boom')
      const wrapper = await mountSuspended(LoginPage)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Login failed',
        description: 'Something went wrong',
        color: 'error'
      })
    })
  })

  describe('Google OAuth', () => {
    it('calls signInWithOAuth with the google provider and a /confirm redirectTo tagged as the OAuth flow', async () => {
      const wrapper = await mountSuspended(LoginPage)

      const googleButton = wrapper.findAll('button').find(b => b.text().includes('Google'))
      expect(googleButton).toBeTruthy()

      await googleButton!.trigger('click')

      expect(signInWithOAuthMock).toHaveBeenCalledTimes(1)
      const [args] = signInWithOAuthMock.mock.calls[0]
      expect(args.provider).toBe('google')

      // /confirm serves both the email-confirmation link and this callback, and
      // the two need different screens. We own this URL, so tag it rather than
      // leaving /confirm to infer the flow.
      const redirectTo = new URL(args.options.redirectTo)
      expect(redirectTo.pathname).toBe('/confirm')
      expect(redirectTo.searchParams.get('flow')).toBe('oauth')
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('shows an "Auth Error" toast when signInWithOAuth returns an error', async () => {
      signInWithOAuthMock.mockResolvedValue({ error: new Error('OAuth provider unavailable') })
      const wrapper = await mountSuspended(LoginPage)

      const googleButton = wrapper.findAll('button').find(b => b.text().includes('Google'))
      await googleButton!.trigger('click')

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Auth Error',
        description: 'OAuth provider unavailable',
        color: 'error'
      })
    })
  })
})
