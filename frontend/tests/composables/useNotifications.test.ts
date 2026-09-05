import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useNotifications } from '../../app/composables/useNotifications'

const userRef = ref<Record<string, unknown> | null>(null)
const toastAddMock = vi.fn()

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))
mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    getSession: () => Promise.resolve({ data: { session: { access_token: 'jwt-token' } } }),
    onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } })
  }
}))

// Every constructed EventSource, so a test can count how many streams the
// composable actually opened and push events through them.
const streams: FakeEventSource[] = []

class FakeEventSource {
  url: string
  closed = false
  onerror: (() => void) | null = null
  private listeners: Record<string, ((e: { data: string }) => void)[]> = {}

  constructor(url: string) {
    this.url = url
    streams.push(this)
  }

  addEventListener(type: string, fn: (e: { data: string }) => void) {
    (this.listeners[type] ||= []).push(fn)
  }

  emit(payload: Record<string, unknown>) {
    for (const fn of this.listeners.message || []) fn({ data: JSON.stringify(payload) })
  }

  close() {
    this.closed = true
  }
}

// happy-dom ships no EventSource, so without this the composable's
// `new EventSource(...)` throws into its own catch and opens nothing. The
// assignment has to happen per-test: the Nuxt environment hands each test a
// fresh window.
function installFakeEventSource() {
  ;(window as unknown as Record<string, unknown>).EventSource = FakeEventSource
}

const Host = defineComponent({
  setup() {
    return useNotifications()
  },
  template: '<div />'
})

describe('composables/useNotifications', () => {
  beforeEach(() => {
    userRef.value = null
    toastAddMock.mockClear()
    streams.length = 0
    installFakeEventSource()
  })

  afterEach(() => {
    // The stream is session-scoped, so drop it between tests.
    userRef.value = null
  })

  it('initializes with hasUnread as false and unreadCount as 0', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.clearUnread()
    expect(wrapper.vm.hasUnread).toBe(false)
    expect(wrapper.vm.unreadCount).toBe(0)
  })

  it('clearUnread resets hasUnread and unreadCount', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.hasUnread = true
    wrapper.vm.unreadCount = 5

    wrapper.vm.clearUnread()

    expect(wrapper.vm.hasUnread).toBe(false)
    expect(wrapper.vm.unreadCount).toBe(0)
  })

  describe('the notification stream', () => {
    it('opens a single stream no matter how many components ask for one', async () => {
      // AppHeader re-mounts on every layout change; each mount used to open a
      // stream of its own that nothing closed, so the broker fanned one seller
      // message out as N toasts.
      const first = await mountSuspended(Host)
      await first.vm.connect()
      const second = await mountSuspended(Host)
      await second.vm.connect()
      await flushPromises()

      expect(streams.filter(s => !s.closed)).toHaveLength(1)

      streams[0]!.emit({ type: 'new_message', message: 'Hi', source: 'admin' })
      expect(toastAddMock).toHaveBeenCalledTimes(1)

      first.vm.disconnect()
    })

    it('reopens after the stream is explicitly disconnected', async () => {
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()
      expect(streams.filter(s => !s.closed)).toHaveLength(1)

      wrapper.vm.disconnect()
      expect(streams[0]!.closed).toBe(true)

      await wrapper.vm.connect()
      await flushPromises()
      expect(streams).toHaveLength(2)
      expect(streams[1]!.closed).toBe(false)

      wrapper.vm.disconnect()
    })

    it('titles the toast by who sent it', async () => {
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()

      streams[0]!.emit({ type: 'new_message', message: 'On my way', source: 'admin' })
      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({
        title: 'New message from Seller',
        description: 'On my way'
      }))

      streams[0]!.emit({ type: 'new_message', message: 'RM950 then', source: 'ai' })
      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({
        title: 'New message from Nego-Lah',
        description: 'RM950 then'
      }))

      wrapper.vm.disconnect()
    })
  })

  it('exposes requestNotificationPermission function', async () => {
    const wrapper = await mountSuspended(Host)
    expect(typeof wrapper.vm.requestNotificationPermission).toBe('function')
    await expect(wrapper.vm.requestNotificationPermission()).resolves.toBeUndefined()
  })
})
