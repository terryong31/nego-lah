import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import ForgotPasswordPage from '~/pages/forgot-password.vue'
import { ref } from 'vue'
import { makeAuthStub } from '../helpers/auth'

const userRef = ref<{ id: string } | null>(null)
const authStub = makeAuthStub(userRef)

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

mockNuxtImport('useAuth', () => () => authStub)

mockNuxtImport('useToast', () => () => ({
  add: toastAddMock
}))

async function fillAndSubmit(wrapper: Awaited<ReturnType<typeof mountSuspended>>, email = 'user@example.com') {
  await wrapper.find('input[type="email"]').setValue(email)
  await wrapper.find('form').trigger('submit')
  // let the async onSubmit handler (multiple chained awaits) settle
  await flushPromises()
}

describe('pages/forgot-password.vue', () => {
  beforeEach(() => {
    authStub.forgotPassword.mockReset().mockResolvedValue({ sent: true })
    toastAddMock.mockReset()
  })

  it('renders the forgot-password form fields and footer link', async () => {
    const wrapper = await mountSuspended(ForgotPasswordPage)

    expect(wrapper.text()).toContain('Forgot password')
    expect(wrapper.text()).toContain('Enter your email and we\'ll send you a reset link.')
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Remembered it?')
    expect(wrapper.find('a[href="/login"]').exists()).toBe(true)
    // Confirmation panel must not be shown up front
    expect(wrapper.text()).not.toContain('Email sent')
  })

  it('does not attempt a reset when the schema validation fails', async () => {
    const wrapper = await mountSuspended(ForgotPasswordPage)

    await fillAndSubmit(wrapper, 'not-an-email')

    expect(authStub.forgotPassword).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Invalid email')
  })

  describe('successful submission', () => {
    it('asks the backend to send the link, and lets it decide where the link lands', async () => {
      const wrapper = await mountSuspended(ForgotPasswordPage)

      await fillAndSubmit(wrapper, 'user@example.com')

      // SPEC-093: the link in the email points at the API's callback, which
      // redeems it server-side and 302s back with the session already set. The
      // page no longer chooses where it lands — the backend does.
      expect(authStub.forgotPassword).toHaveBeenCalledTimes(1)
      const [email] = authStub.forgotPassword.mock.calls[0]!
      expect(email).toBe('user@example.com')
    })

    it('shows a success toast', async () => {
      const wrapper = await mountSuspended(ForgotPasswordPage)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Check your inbox',
        description: 'We sent you a password reset link.',
        color: 'success'
      })
    })

    it('flips the UI to the "check your inbox" confirmation panel instead of showing the form', async () => {
      const wrapper = await mountSuspended(ForgotPasswordPage)

      await fillAndSubmit(wrapper)

      expect(wrapper.text()).toContain('Email sent')
      expect(wrapper.text()).toContain('If an account exists for that email, you\'ll receive a link to reset your password.')
      expect(wrapper.find('a[href="/login"]').exists()).toBe(true)
      expect(wrapper.text()).toMatch(/back to login/i)
      // The form (and its email input) should no longer be rendered
      expect(wrapper.find('input[type="email"]').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('Forgot password')
    })
  })

  describe('submission failure', () => {
    it('shows a "Request failed" toast and keeps the form visible', async () => {
      authStub.forgotPassword.mockRejectedValue(new Error('Rate limit exceeded'))
      const wrapper = await mountSuspended(ForgotPasswordPage)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Request failed',
        description: 'Rate limit exceeded',
        color: 'error'
      })
      expect(wrapper.text()).not.toContain('Email sent')
      expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      authStub.forgotPassword.mockRejectedValue('boom')
      const wrapper = await mountSuspended(ForgotPasswordPage)

      await fillAndSubmit(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Request failed',
        description: 'Something went wrong',
        color: 'error'
      })
      expect(wrapper.text()).not.toContain('Email sent')
    })
  })
})
