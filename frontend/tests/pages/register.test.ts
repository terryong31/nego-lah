import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import RegisterPage from '~/pages/register.vue'

const { signUpMock } = vi.hoisted(() => ({
  signUpMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    signUp: signUpMock
  }
}))

mockNuxtImport('useToast', () => () => ({
  add: toastAddMock
}))

// Note: useRouter is deliberately left un-mocked (see tests/pages/login.test.ts for
// precedent). A partial stub like `{ push: vi.fn() }` breaks Nuxt's own internal
// client plugins (chunk-reload, navigation-repaint, ...) which call real router
// methods (`router.beforeEach`/`afterEach`/`beforeResolve`) during app init. Instead
// we spy on the real router's `push` method per-test via `wrapper.vm.$router`.
function spyOnRouterPush(wrapper: { vm: { $router: { push: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'push').mockImplementation(() => Promise.resolve())
}

async function fillAndSubmit(
  wrapper: Awaited<ReturnType<typeof mountSuspended>>,
  email = 'user@example.com',
  password = 'password123',
  confirmPassword = password
) {
  await wrapper.find('input[type="email"]').setValue(email)
  const passwordInputs = wrapper.findAll('input[type="password"]')
  await passwordInputs[0]!.setValue(password)
  await passwordInputs[1]!.setValue(confirmPassword)
  await wrapper.find('form').trigger('submit')
  // let the async onSubmit handler (multiple chained awaits) settle
  await flushPromises()
}

describe('pages/register.vue', () => {
  beforeEach(() => {
    signUpMock.mockReset().mockResolvedValue({
      data: { user: { id: 'user-1', identities: [{ id: 'identity-1' }] } },
      error: null
    })
    toastAddMock.mockReset()
  })

  it('renders the register form fields and footer link', async () => {
    const wrapper = await mountSuspended(RegisterPage)

    expect(wrapper.text()).toContain('Register')
    expect(wrapper.text()).toContain('Create a new account to start buying and negotiating.')
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    expect(wrapper.findAll('input[type="password"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('Already have an account?')
    expect(wrapper.find('a[href="/login"]').exists()).toBe(true)
  })

  it('does not attempt sign-up when the schema validation fails on email/password format', async () => {
    const wrapper = await mountSuspended(RegisterPage)

    await fillAndSubmit(wrapper, 'not-an-email', 'short', 'short')

    expect(signUpMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Invalid email')
    expect(wrapper.text()).toContain('Must be at least 8 characters')
  })

  it('shows a "Passwords don\'t match" error and does not sign up when password/confirmPassword differ', async () => {
    const wrapper = await mountSuspended(RegisterPage)

    await fillAndSubmit(wrapper, 'user@example.com', 'password123', 'differentPass1')

    expect(signUpMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Passwords don\'t match')
  })

  describe('successful registration', () => {
    it('signs up, shows a success toast, and redirects to /login', async () => {
      const wrapper = await mountSuspended(RegisterPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'user@example.com', 'password123')

      expect(signUpMock).toHaveBeenCalledWith({ email: 'user@example.com', password: 'password123' })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Registration successful',
        description: 'Please check your email to verify your account.',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith({ path: '/login' })
    })
  })

  describe('anti-enumeration: email already registered', () => {
    it('shows an "Email already registered" warning toast and redirects to /login without a success toast', async () => {
      signUpMock.mockResolvedValue({
        data: { user: { id: 'user-1', identities: [] } },
        error: null
      })
      const wrapper = await mountSuspended(RegisterPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Email already registered',
        description: 'This email already has an account. If you signed up with Google, use the Google button.',
        color: 'warning'
      })
      expect(pushSpy).toHaveBeenCalledWith({ path: '/login' })
    })

    it('treats a missing identities field (undefined) the same as an empty array', async () => {
      signUpMock.mockResolvedValue({
        data: { user: { id: 'user-1', identities: undefined } },
        error: null
      })
      const wrapper = await mountSuspended(RegisterPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Email already registered' }))
      expect(pushSpy).toHaveBeenCalledWith({ path: '/login' })
    })
  })

  describe('registration failure', () => {
    it('shows a "Registration failed" toast with the Supabase error message and does not redirect', async () => {
      signUpMock.mockResolvedValue({ data: { user: null }, error: new Error('User already registered') })
      const wrapper = await mountSuspended(RegisterPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Registration failed',
        description: 'User already registered',
        color: 'error'
      })
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      signUpMock.mockRejectedValue('boom')
      const wrapper = await mountSuspended(RegisterPage)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Registration failed',
        description: 'Something went wrong',
        color: 'error'
      })
    })
  })
})
