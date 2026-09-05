import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockComponent, mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import LoginPage from '~/pages/_console/login.vue'

const { callMock } = vi.hoisted(() => ({
  callMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

const { navigateToMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))
mockNuxtImport('navigateTo', () => navigateToMock)

// The real UPinInput (reka-ui backed) renders one native <input> per digit and
// wires up complex focus/paste logic that isn't worth exercising here. Stub it
// with a single text input that mirrors modelValue as an array of characters
// and emits 'complete' once it reaches `length`, matching the parent's
// `v-model="code"` / `@complete="submitOtp"` contract.
mockComponent('UPinInput', {
  props: {
    modelValue: { type: Array, default: () => [] },
    length: { type: [Number, String], default: 6 },
    otp: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false }
  },
  emits: ['update:modelValue', 'complete'],
  template: `<input
    data-testid="otp-input"
    :value="(modelValue || []).join('')"
    :disabled="disabled"
    @input="onInput($event)"
  />`,
  methods: {
    onInput(e: Event) {
      const value = (e.target as HTMLInputElement).value
      const chars = value.split('')
      this.$emit('update:modelValue', chars)
      if (chars.length >= Number(this.length)) {
        this.$emit('complete', chars)
      }
    }
  }
})

async function fillPassword(wrapper: VueWrapper, email = 'admin@example.com', password = 'super-secret') {
  await wrapper.find('input[type="email"]').setValue(email)
  await wrapper.find('input[type="password"]').setValue(password)
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

async function fillOtp(wrapper: VueWrapper, code = '123456') {
  await wrapper.find('[data-testid="otp-input"]').setValue(code)
  await flushPromises()
}

describe('pages/_console/login.vue', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    navigateToMock.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('renders the password step by default', async () => {
    wrapper = await mountSuspended(LoginPage)

    expect(wrapper.text()).toContain('Admin Console')
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="otp-input"]').exists()).toBe(false)
  })

  describe('submitPassword', () => {
    it('does not call the API when email or password is empty', async () => {
      wrapper = await mountSuspended(LoginPage)

      // Only fill email, leave password blank, then submit the form directly
      // (bypassing the disabled submit button) to exercise the guard clause.
      await wrapper.find('input[type="email"]').setValue('admin@example.com')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(callMock).not.toHaveBeenCalled()
    })

    it('transitions from the password step to the OTP step, stores the handle, and shows an info toast', async () => {
      callMock.mockResolvedValue({ handle: 'handle-123', message: 'We sent a code to your email' })
      wrapper = await mountSuspended(LoginPage)

      await fillPassword(wrapper, 'admin@example.com', 'super-secret')

      expect(callMock).toHaveBeenCalledWith('/auth/login', {
        method: 'POST',
        body: { email: 'admin@example.com', password: 'super-secret' }
      })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Check your email',
        description: 'We sent a code to your email',
        color: 'info'
      })

      // Now on the OTP step.
      expect(wrapper.find('input[type="password"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="otp-input"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('admin@example.com')
      expect(wrapper.text()).toContain('6-digit code')
    })

    it('shows a "Login failed" toast with the server detail message on failure and stays on the password step', async () => {
      callMock.mockRejectedValue({ data: { detail: 'Invalid email or password' } })
      wrapper = await mountSuspended(LoginPage)

      await fillPassword(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Login failed',
        description: 'Invalid email or password',
        color: 'error'
      })
      expect(wrapper.find('input[type="password"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="otp-input"]').exists()).toBe(false)
    })

    it('falls back to a generic message when the error has no detail', async () => {
      callMock.mockRejectedValue(new Error('network down'))
      wrapper = await mountSuspended(LoginPage)

      await fillPassword(wrapper)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Login failed',
        description: 'Invalid credentials',
        color: 'error'
      })
    })
  })

  describe('submitOtp', () => {
    async function goToOtpStep(w: VueWrapper) {
      callMock.mockResolvedValueOnce({ handle: 'handle-123', message: 'Code sent' })
      await fillPassword(w)
      callMock.mockReset()
    }

    it('auto-submits once the 6-digit OTP is complete, verifies it, shows a success toast, and redirects', async () => {
      wrapper = await mountSuspended(LoginPage)
      await goToOtpStep(wrapper)

      callMock.mockResolvedValue({ ok: true })

      await fillOtp(wrapper, '123456')

      expect(callMock).toHaveBeenCalledWith('/auth/verify-2fa', {
        method: 'POST',
        body: { handle: 'handle-123', code: '123456' }
      })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Welcome back', color: 'success' })
      expect(navigateToMock).toHaveBeenCalledWith('/_console')
    })

    it('clears the code and shows an error toast when verification fails', async () => {
      wrapper = await mountSuspended(LoginPage)
      await goToOtpStep(wrapper)

      callMock.mockRejectedValue({ data: { detail: 'Code expired' } })

      await fillOtp(wrapper, '123456')

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Verification failed',
        description: 'Code expired',
        color: 'error'
      })
      expect(navigateToMock).not.toHaveBeenCalled()
      // The pin input should be cleared back to empty after the failure.
      expect((wrapper.find('[data-testid="otp-input"]').element as HTMLInputElement).value).toBe('')
    })

    it('falls back to a generic message when the verification error has no detail', async () => {
      wrapper = await mountSuspended(LoginPage)
      await goToOtpStep(wrapper)

      callMock.mockRejectedValue(new Error('boom'))

      await fillOtp(wrapper, '123456')

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Verification failed',
        description: 'Invalid or expired code',
        color: 'error'
      })
    })

    it('does not call the API when the code is shorter than 6 digits', async () => {
      wrapper = await mountSuspended(LoginPage)
      await goToOtpStep(wrapper)

      await wrapper.find('[data-testid="otp-input"]').setValue('123')
      await flushPromises()

      expect(callMock).not.toHaveBeenCalled()
    })
  })

  describe('back', () => {
    it('resets to the password step, clearing the code and password', async () => {
      wrapper = await mountSuspended(LoginPage)
      callMock.mockResolvedValueOnce({ handle: 'handle-123', message: 'Code sent' })
      await fillPassword(wrapper, 'admin@example.com', 'super-secret')

      // Confirm we're on the OTP step first.
      expect(wrapper.find('[data-testid="otp-input"]').exists()).toBe(true)

      const backButton = wrapper.findAll('button').find(b => b.text() === 'Back')
      expect(backButton).toBeTruthy()
      await backButton!.trigger('click')
      await flushPromises()

      // Back on the password step, with a blank password field.
      expect(wrapper.find('input[type="password"]').exists()).toBe(true)
      expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
      expect(wrapper.find('[data-testid="otp-input"]').exists()).toBe(false)
    })
  })
})
