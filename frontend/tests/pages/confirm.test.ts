import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import ConfirmPage from '~/pages/confirm.vue'

const userRef = ref<{ id: string, email: string } | null>(null)
const routeStub = reactive<{ query: Record<string, string | undefined>, hash?: string }>({ query: {} })

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useRoute', () => () => routeStub)

function spyOnRouterPush(wrapper: { vm: { $router: { push: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'push').mockImplementation(() => Promise.resolve())
}

describe('pages/confirm.vue', () => {
  let wrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

  beforeEach(() => {
    vi.useFakeTimers()
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
    routeStub.query = { redirect: '/items/item-1' }
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    await flushPromises()

    const button = wrapper.findComponent({ name: 'UButton' })
    await button.trigger('click')

    expect(pushSpy).toHaveBeenCalledWith('/items/item-1')
  })

  it('auto-redirects to / after countdown expires', async () => {
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
