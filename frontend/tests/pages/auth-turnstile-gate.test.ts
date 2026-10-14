import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockComponent, mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import ForgotPasswordPage from '~/pages/forgot-password.vue'
import LoginPage from '~/pages/login.vue'
import RegisterPage from '~/pages/register.vue'
import { makeAuthStub } from '../helpers/auth'

// The buyer auth forms used to leave their submit button live while the
// Turnstile challenge was unsolved: a click only produced a "complete the
// security check" toast. The button is now disabled until there is a token,
// and disabled again once that single-use token has been spent.

const { toastAddMock, callMock, resetMock, captured } = vi.hoisted(() => ({
  toastAddMock: vi.fn(),
  callMock: vi.fn(),
  resetMock: vi.fn(),
  captured: { options: {} as Record<string, unknown> }
}))

const userRef = ref<{ id: string } | null>(null)
const authStub = makeAuthStub(userRef)
const turnstileEnabled = ref(true)
const turnstileToken = ref<string | undefined>(undefined)

mockNuxtImport('useAuth', () => () => authStub)
mockNuxtImport('useApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))
mockNuxtImport('useTurnstileToken', () => () => ({
  token: turnstileToken,
  isEnabled: turnstileEnabled,
  isReady: ref(false),
  setToken: (t: string | undefined) => { turnstileToken.value = t },
  clearToken: () => { turnstileToken.value = undefined }
}))

// Stands in for Cloudflare's widget: a click solves it, and it exposes the
// same `reset()` the real component does.
mockComponent('NuxtTurnstile', defineComponent({
  props: {
    modelValue: { type: String, default: undefined },
    options: { type: Object, default: () => ({}) }
  },
  emits: ['update:modelValue'],
  setup(props, { emit, expose }) {
    captured.options = props.options as Record<string, unknown>
    expose({ reset: resetMock })
    return () => h('button', {
      'data-testid': 'turnstile',
      'type': 'button',
      'onClick': () => emit('update:modelValue', 'solved-token')
    }, 'turnstile')
  }
}))

type Wrapper = VueWrapper

const pages = [
  {
    name: 'login',
    page: LoginPage,
    action: 'login',
    fail: () => authStub.login.mockRejectedValue({ data: { detail: 'Invalid login credentials' } }),
    fill: async (w: Wrapper) => {
      await w.find('input[type="email"]').setValue('user@example.com')
      await w.find('input[type="password"]').setValue('password123')
    }
  },
  {
    name: 'register',
    page: RegisterPage,
    action: 'register',
    fail: () => authStub.register.mockRejectedValue({ data: { detail: 'Could not create that account' } }),
    fill: async (w: Wrapper) => {
      await w.find('input[type="email"]').setValue('user@example.com')
      const passwords = w.findAll('input[type="password"]')
      await passwords[0]!.setValue('password123')
      await passwords[1]!.setValue('password123')
    }
  },
  {
    name: 'forgot-password',
    page: ForgotPasswordPage,
    action: 'forgot-password',
    fail: () => authStub.forgotPassword.mockRejectedValue(new Error('down')),
    fill: async (w: Wrapper) => {
      await w.find('input[type="email"]').setValue('user@example.com')
    }
  }
]

function submitButton(wrapper: Wrapper) {
  return wrapper.find('button[type="submit"]')
}

describe.each(pages)('pages/$name.vue — Turnstile gate on the submit button', ({ page, action, fill, fail }) => {
  let wrapper: Wrapper | undefined

  beforeEach(() => {
    userRef.value = null
    turnstileEnabled.value = true
    turnstileToken.value = undefined
    toastAddMock.mockReset()
    callMock.mockReset().mockResolvedValue({ ok: true })
    resetMock.mockReset()
    authStub.login.mockReset()
    authStub.register.mockReset()
    authStub.forgotPassword.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('keeps the button disabled until the challenge is solved', async () => {
    wrapper = await mountSuspended(page)

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="turnstile"]').trigger('click')

    expect(submitButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('does not gate the button when Turnstile is off', async () => {
    turnstileEnabled.value = false
    wrapper = await mountSuspended(page)

    expect(submitButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('spends the token after a failed submit and starts a fresh challenge', async () => {
    fail()
    wrapper = await mountSuspended(page)
    await wrapper.find('[data-testid="turnstile"]').trigger('click')
    await fill(wrapper)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(turnstileToken.value).toBeUndefined()
    expect(resetMock).toHaveBeenCalledTimes(1)
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('locks the button again when the token expires', async () => {
    wrapper = await mountSuspended(page)
    await wrapper.find('[data-testid="turnstile"]').trigger('click')

    expect(captured.options.action).toBe(action)
    ;(captured.options['expired-callback'] as () => void)()
    await flushPromises()

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('drops the token on leaving, so it cannot unlock the next page\'s button', async () => {
    wrapper = await mountSuspended(page)
    await wrapper.find('[data-testid="turnstile"]').trigger('click')

    wrapper.unmount()
    wrapper = undefined

    expect(turnstileToken.value).toBeUndefined()
  })
})
