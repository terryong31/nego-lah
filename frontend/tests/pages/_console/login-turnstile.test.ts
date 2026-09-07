import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockComponent, mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import LoginPage from '~/pages/_console/login.vue'

// SPEC-044 D: `POST /admin/auth/login` is now Turnstile-gated on the backend —
// the only unauthenticated credential endpoint in the system. This is the
// console's half of that: without a widget here, the operator simply cannot
// log in once the backend starts enforcing.
//
// The header name matters and is asserted literally: the backend reads
// `X-Turnstile-Token` (or Cloudflare's own `cf-turnstile-response`), and a
// mismatch fails silently as "no token supplied" rather than as an error.

const { callMock, toastAddMock, navigateToMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn(),
  navigateToMock: vi.fn()
}))

const turnstileEnabled = ref(true)
const turnstileToken = ref<string | undefined>(undefined)

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))
mockNuxtImport('navigateTo', () => navigateToMock)
mockNuxtImport('useTurnstileToken', () => () => ({
  token: turnstileToken,
  isEnabled: turnstileEnabled,
  isReady: ref(Boolean(turnstileToken.value)),
  setToken: (t: string | undefined) => { turnstileToken.value = t },
  clearToken: () => { turnstileToken.value = undefined }
}))

// The real widget talks to Cloudflare. This stub stands in for it and lets a
// test hand the page a token the same way a solved challenge would.
mockComponent('NuxtTurnstile', {
  props: {
    modelValue: { type: String, default: undefined },
    options: { type: Object, default: () => ({}) }
  },
  emits: ['update:modelValue'],
  template: `<button
    data-testid="turnstile"
    type="button"
    @click="$emit('update:modelValue', 'solved-token')"
  >turnstile</button>`
})

async function submitPassword(wrapper: VueWrapper) {
  await wrapper.find('input[type="email"]').setValue('admin@example.com')
  await wrapper.find('input[type="password"]').setValue('super-secret')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

describe('pages/_console/login.vue — Turnstile gate', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    navigateToMock.mockReset()
    turnstileEnabled.value = true
    turnstileToken.value = undefined
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('renders the challenge when Turnstile is enabled', async () => {
    wrapper = await mountSuspended(LoginPage)

    expect(wrapper.find('[data-testid="turnstile"]').exists()).toBe(true)
  })

  it('does not render the challenge when Turnstile is disabled', async () => {
    turnstileEnabled.value = false
    wrapper = await mountSuspended(LoginPage)

    expect(wrapper.find('[data-testid="turnstile"]').exists()).toBe(false)
  })

  it('refuses to submit until the challenge is solved, and says why', async () => {
    wrapper = await mountSuspended(LoginPage)

    await submitPassword(wrapper)

    expect(callMock).not.toHaveBeenCalled()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ color: 'error' })
    )
  })

  it('sends the solved token as X-Turnstile-Token', async () => {
    callMock.mockResolvedValue({ handle: 'handle-123', message: 'Code sent' })
    wrapper = await mountSuspended(LoginPage)

    await wrapper.find('[data-testid="turnstile"]').trigger('click')
    await submitPassword(wrapper)

    expect(callMock).toHaveBeenCalledWith('/auth/login', {
      method: 'POST',
      body: { email: 'admin@example.com', password: 'super-secret' },
      headers: { 'X-Turnstile-Token': 'solved-token' }
    })
  })

  it('sends no Turnstile header at all when the challenge is disabled', async () => {
    // Development, where the backend bypasses verification. Sending an empty
    // header would be read as a supplied-but-blank token the day the bypass is
    // removed, so the key has to be absent rather than empty.
    turnstileEnabled.value = false
    callMock.mockResolvedValue({ handle: 'handle-123', message: 'Code sent' })
    wrapper = await mountSuspended(LoginPage)

    await submitPassword(wrapper)

    expect(callMock).toHaveBeenCalledWith('/auth/login', {
      method: 'POST',
      body: { email: 'admin@example.com', password: 'super-secret' }
    })
  })

  it('clears the token after a failed attempt so a fresh challenge is solved', async () => {
    // Siteverify tokens are single-use: replaying one produces
    // `timeout-or-duplicate` and a 403, which would look to the operator like
    // their password was wrong on every retry.
    callMock.mockRejectedValue({ data: { detail: 'Invalid credentials' } })
    wrapper = await mountSuspended(LoginPage)

    await wrapper.find('[data-testid="turnstile"]').trigger('click')
    await submitPassword(wrapper)

    expect(callMock).toHaveBeenCalledTimes(1)
    expect(turnstileToken.value).toBeUndefined()
  })
})
