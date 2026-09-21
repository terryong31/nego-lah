import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import LoginPage from '~/pages/login.vue'
import { makeAuthStub } from '../helpers/auth'

const userRef = ref<{ id: string } | null>(null)
const authStub = makeAuthStub(userRef)

const { callMock } = vi.hoisted(() => ({
  callMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

mockNuxtImport('useAuth', () => () => authStub)

mockNuxtImport('useApi', () => () => ({
  call: callMock
}))

mockNuxtImport('useToast', () => () => ({
  add: toastAddMock
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
    userRef.value = null
    authStub.login.mockReset().mockImplementation(async () => {
      userRef.value = { id: 'user-1' }
      return userRef.value
    })
    authStub.signInWithProvider.mockReset()
    callMock.mockReset().mockResolvedValue({ ok: true })
    toastAddMock.mockReset()
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

    expect(authStub.login).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Invalid email')
    expect(wrapper.text()).toContain('Must be at least 8 characters')
  })

  describe('successful password login', () => {
    it('signs in, probes the banned-account endpoint with the new user id, shows a success toast, and redirects home', async () => {
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(authStub.login).toHaveBeenCalledWith('user@example.com', 'password123', undefined)
      expect(callMock).toHaveBeenCalledWith('/user/user-1/account')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Welcome back!',
        description: 'You have logged in successfully.',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith('/')
    })

    it('refuses an offsite redirect target and goes home instead', async () => {
      const wrapper = await mountSuspended(LoginPage, {
        route: '/login?redirect=%2F%2Fevil.com%2Fchat'
      })
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(pushSpy).toHaveBeenCalledWith('/')
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

      expect(authStub.login).toHaveBeenCalledTimes(1)
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
    it('shows a "Login failed" toast with the server\'s own message and does not redirect', async () => {
      // The backend answers wrong password, unknown address and unconfirmed
      // account with one message, on purpose — so it is safe to show verbatim.
      authStub.login.mockRejectedValue({ data: { detail: 'Invalid email or password' } })
      const wrapper = await mountSuspended(LoginPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Login failed',
        description: 'Invalid email or password',
        color: 'error'
      })
      expect(callMock).not.toHaveBeenCalled()
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      authStub.login.mockRejectedValue('boom')
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
    it('hands the browser to the API, which owns the exchange', async () => {
      // SPEC-093: a full navigation to /auth/oauth/start. The authorization
      // code goes to the backend and never reaches this tab, so there is no
      // SDK call to make and no error for this page to catch.
      const wrapper = await mountSuspended(LoginPage)

      const googleButton = wrapper.findAll('button').find(b => b.text().includes('Google'))
      expect(googleButton).toBeTruthy()

      await googleButton!.trigger('click')

      expect(authStub.signInWithProvider).toHaveBeenCalledWith('google', '/')
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('carries the page the visitor was bounced from', async () => {
      const wrapper = await mountSuspended(LoginPage, {
        route: '/login?redirect=%2Fchat%3Fitem_id%3Ditem-9'
      })

      const googleButton = wrapper.findAll('button').find(b => b.text().includes('Google'))
      await googleButton!.trigger('click')

      expect(authStub.signInWithProvider).toHaveBeenCalledWith('google', '/chat?item_id=item-9')
    })
  })
})
