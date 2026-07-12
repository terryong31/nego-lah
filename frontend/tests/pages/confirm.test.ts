import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import ConfirmPage from '~/pages/confirm.vue'

// A real Vue ref (not a hand-rolled stand-in) is required here, unlike some
// other test files: this page's `watch(user, ...)` needs genuine reactivity
// so that mutating `.value` *after* mount actually re-fires the watcher.
const userRef = ref<{ id: string, email: string } | null>(null)

mockNuxtImport('useSupabaseUser', () => () => userRef)

// Note: useRouter is deliberately left un-mocked (see tests/pages/login.test.ts
// and tests/components/AppHeader.test.ts for precedent) — a partial stub like
// `{ push: vi.fn() }` breaks Nuxt's own internal client plugins which call real
// router methods during app init. Instead we spy on the real router's `push`
// method per-test via `wrapper.vm.$router`.
function spyOnRouterPush(wrapper: { vm: { $router: { push: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'push').mockImplementation(() => Promise.resolve())
}

describe('pages/confirm.vue', () => {
  // Each `mountSuspended` call sets up a fresh `watch(user, ...)` tied to that
  // component instance. Because all instances in this file share the same
  // module-level `userRef` (and the same underlying Nuxt test app / router
  // singleton), a still-mounted component from a previous test would also
  // react to later mutations of `userRef.value` and pollute the next test's
  // push-spy call count. Unmount after every test to stop that watcher.
  let wrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

  beforeEach(() => {
    userRef.value = null
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('renders a loading indicator and confirming message', async () => {
    wrapper = await mountSuspended(ConfirmPage)

    expect(wrapper.findComponent({ name: 'UProgress' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('Confirming your session, please wait...')
  })

  it('does not redirect immediately when there is no user on mount (immediate watch, falsy value)', async () => {
    userRef.value = null
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    await flushPromises()

    expect(pushSpy).not.toHaveBeenCalled()
  })

  it('redirects to / once the user ref becomes truthy after mount', async () => {
    userRef.value = null
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    expect(pushSpy).not.toHaveBeenCalled()

    userRef.value = { id: 'u1', email: 'user@example.com' }
    await flushPromises()

    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(pushSpy).toHaveBeenCalledWith('/')
  })

  it('does not redirect again when the user ref changes to a different truthy value more than once', async () => {
    userRef.value = null
    wrapper = await mountSuspended(ConfirmPage)
    const pushSpy = spyOnRouterPush(wrapper)

    userRef.value = { id: 'u1', email: 'user@example.com' }
    await flushPromises()
    expect(pushSpy).toHaveBeenCalledTimes(1)

    // Simulate the user switching back to null and then truthy again — each
    // truthy transition should fire another push('/').
    userRef.value = null
    await flushPromises()
    expect(pushSpy).toHaveBeenCalledTimes(1)

    userRef.value = { id: 'u2', email: 'other@example.com' }
    await flushPromises()
    expect(pushSpy).toHaveBeenCalledTimes(2)
    expect(pushSpy).toHaveBeenLastCalledWith('/')
  })
})
