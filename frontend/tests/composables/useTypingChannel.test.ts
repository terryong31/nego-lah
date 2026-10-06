/**
 * SPEC-094 — typing presence over the authenticated broker.
 *
 * This used to be a Supabase Realtime broadcast channel, `chat:{userId}`,
 * created with no `private: true` and with no policy on `realtime.messages`.
 * The anon key ships in this bundle, so that channel was readable by anyone
 * holding it and a user id: a stranger could watch a buyer's negotiation live.
 *
 * The protocol did not change — a role on each ping, a 3s idle expiry, a 1.5s
 * send throttle — only what carries it. So these tests are about the transport:
 * the buyer rides the stream `useNotifications` already holds, the admin console
 * opens its own against the admin cookie, and neither can address a conversation
 * that is not theirs.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useTypingChannel } from '../../app/composables/useTypingChannel'

// The bus `useNotifications` fans its stream out on. Captured so a test can
// push events at the composable the way the server would.
const { handlers, onChatStreamEventMock } = vi.hoisted(() => {
  const handlers: ((event: Record<string, unknown>) => void)[] = []
  return {
    handlers,
    onChatStreamEventMock: vi.fn((handler: (event: Record<string, unknown>) => void) => {
      handlers.push(handler)
      return () => {
        const i = handlers.indexOf(handler)
        if (i >= 0) handlers.splice(i, 1)
      }
    })
  }
})

vi.mock('../../app/composables/useNotifications', () => ({
  onChatStreamEvent: onChatStreamEventMock
}))

mockNuxtImport('getCsrfToken', () => () => 'admin-csrf')

// Nuxt 4.5 made `$fetch` an auto-import (from `#build/fetch.mjs`), so it is
// mocked like any other import; stubbing the global no longer reaches it.
mockNuxtImport('$fetch', () => fetchMock)

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))
const streams: FakeEventSource[] = []

class FakeEventSource {
  url: string
  withCredentials: boolean
  closed = false
  onerror: (() => void) | null = null
  private listeners: Record<string, ((e: { data: string }) => void)[]> = {}

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url
    this.withCredentials = Boolean(init?.withCredentials)
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

/** Push an event down the buyer's shared stream. */
function emitToBus(payload: Record<string, unknown>) {
  for (const handler of [...handlers]) handler(payload)
}

const Host = defineComponent({
  setup() {
    return useTypingChannel()
  },
  template: '<div />'
})

describe('composables/useTypingChannel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    handlers.length = 0
    streams.length = 0
    onChatStreamEventMock.mockClear()
    fetchMock.mockReset().mockResolvedValue({})
    ;(window as unknown as Record<string, unknown>).EventSource = FakeEventSource
    document.cookie = 'nl_csrf=buyer-csrf'
  })

  describe('the buyer side', () => {
    it('listens on the stream the session already holds open, opening none of its own', async () => {
      const wrapper = await mountSuspended(Host)

      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer' })

      expect(onChatStreamEventMock).toHaveBeenCalledTimes(1)
      expect(streams).toHaveLength(0)
    })

    it('raises the indicator for the other party and expires it after an idle window', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer' })

      emitToBus({ type: 'typing', role: 'seller' })
      expect(wrapper.vm.remoteTyping).toBe(true)

      vi.advanceTimersByTime(3000)
      expect(wrapper.vm.remoteTyping, 'typing carries no "stopped" signal').toBe(false)
    })

    it('ignores its own ping coming back down the same stream', async () => {
      // Both parties are on one per-user channel, so everything published to it
      // is echoed to the sender too — the role is what tells them apart.
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer' })

      emitToBus({ type: 'typing', role: 'customer' })

      expect(wrapper.vm.remoteTyping).toBe(false)
    })

    it('hands live messages to the caller', async () => {
      const onMessage = vi.fn()
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer', onMessage })

      emitToBus({ type: 'new_message', message: 'RM240 can lah', source: 'ai' })

      expect(onMessage).toHaveBeenCalledWith({ type: 'new_message', message: 'RM240 can lah', source: 'ai' })
    })

    it('pings the conversation it is signed in as, with no id to tamper with', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer' })

      wrapper.vm.ping()

      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [url, options] = fetchMock.mock.calls[0]!
      expect(url).toBe('http://localhost:8000/chat/typing')
      expect(url).not.toContain('buyer-1')
      expect(options.method).toBe('POST')
      expect(options.credentials).toBe('include')
      expect(options.headers['X-CSRF-Token']).toBe('buyer-csrf')
    })

    it('throttles pings, because every keystroke would otherwise be a request', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer' })

      wrapper.vm.ping()
      wrapper.vm.ping()
      wrapper.vm.ping()
      expect(fetchMock).toHaveBeenCalledTimes(1)

      vi.advanceTimersByTime(1500)
      wrapper.vm.ping()
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('drops a ping when no conversation has been joined', async () => {
      const wrapper = await mountSuspended(Host)

      wrapper.vm.ping()

      expect(fetchMock).not.toHaveBeenCalled()
    })

    it('detaches from the bus on leave, so a stale conversation stops being heard', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'seller', sendAs: 'customer' })

      wrapper.vm.leave()
      emitToBus({ type: 'typing', role: 'seller' })

      expect(wrapper.vm.remoteTyping).toBe(false)
    })
  })

  describe('the admin side', () => {
    it('opens its own stream, on the admin session', async () => {
      const wrapper = await mountSuspended(Host)

      wrapper.vm.join('buyer-1', { listenFor: 'customer', sendAs: 'seller' })

      expect(streams).toHaveLength(1)
      expect(streams[0]!.url).toBe('http://localhost:8000/admin/chats/buyer-1/stream')
      expect(streams[0]!.withCredentials, 'the admin cookie is what authorises this').toBe(true)
      // It must not ride the buyer's bus — the console is not signed in as them.
      expect(onChatStreamEventMock).not.toHaveBeenCalled()
    })

    it('reacts to the customer typing on its own stream', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'customer', sendAs: 'seller' })

      streams[0]!.emit({ type: 'typing', role: 'customer' })

      expect(wrapper.vm.remoteTyping).toBe(true)
    })

    it('pings through the admin route with the admin CSRF token', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'customer', sendAs: 'seller' })

      wrapper.vm.ping()

      const [url, options] = fetchMock.mock.calls[0]!
      expect(url).toBe('http://localhost:8000/admin/chats/buyer-1/typing')
      expect(options.headers['X-CSRF-Token']).toBe('admin-csrf')
    })

    it('closes its stream on leave', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.join('buyer-1', { listenFor: 'customer', sendAs: 'seller' })

      wrapper.vm.leave()

      expect(streams[0]!.closed).toBe(true)
    })
  })
})
