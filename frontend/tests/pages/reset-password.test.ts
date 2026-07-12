import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import ResetPasswordPage from '~/pages/reset-password.vue'

const { updateUserMock } = vi.hoisted(() => ({
  updateUserMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    updateUser: updateUserMock
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
  password = 'password123',
  confirmPassword = password
) {
  const passwordInputs = wrapper.findAll('input[type="password"]')
  await passwordInputs[0]!.setValue(password)
  await passwordInputs[1]!.setValue(confirmPassword)
  await wrapper.find('form').trigger('submit')
  // let the async onSubmit handler (multiple chained awaits) settle
  await flushPromises()
}

describe('pages/reset-password.vue', () => {
  beforeEach(() => {
    updateUserMock.mockReset().mockResolvedValue({ error: null })
    toastAddMock.mockReset()
  })

  it('renders the reset-password form fields', async () => {
    const wrapper = await mountSuspended(ResetPasswordPage)

    expect(wrapper.text()).toContain('Reset password')
    expect(wrapper.text()).toContain('Choose a new password for your account.')
    expect(wrapper.findAll('input[type="password"]')).toHaveLength(2)
  })

  it('does not attempt an update when the schema validation fails on password length', async () => {
    const wrapper = await mountSuspended(ResetPasswordPage)

    await fillAndSubmit(wrapper, 'short', 'short')

    expect(updateUserMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Must be at least 8 characters')
  })

  it('shows a "Passwords don\'t match" error and does not update when password/confirmPassword differ', async () => {
    const wrapper = await mountSuspended(ResetPasswordPage)

    await fillAndSubmit(wrapper, 'password123', 'differentPass1')

    expect(updateUserMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Passwords don\'t match')
  })

  describe('successful submission', () => {
    it('updates the password, shows a success toast, and redirects to /login', async () => {
      const wrapper = await mountSuspended(ResetPasswordPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper, 'password123')

      expect(updateUserMock).toHaveBeenCalledWith({ password: 'password123' })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Password updated',
        description: 'You can now log in with your new password.',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith('/login')
    })
  })

  describe('submission failure', () => {
    it('shows an "Update failed" toast with the Supabase error message and does not redirect', async () => {
      updateUserMock.mockResolvedValue({ error: new Error('Auth session missing') })
      const wrapper = await mountSuspended(ResetPasswordPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Update failed',
        description: 'Auth session missing',
        color: 'error'
      })
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      updateUserMock.mockRejectedValue('boom')
      const wrapper = await mountSuspended(ResetPasswordPage)
      const pushSpy = spyOnRouterPush(wrapper)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Update failed',
        description: 'Something went wrong',
        color: 'error'
      })
      expect(pushSpy).not.toHaveBeenCalled()
    })
  })
})
