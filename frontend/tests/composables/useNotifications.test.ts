import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useNotifications } from '../../app/composables/useNotifications'
import { makeAuthStub } from '../helpers/auth'

const userRef = ref<Record<string, unknown> | null>(null)
const toastAddMock = vi.fn()
// Cloudflare Pages serves the SPA at the directory form of a route, so a hard
// load of the chat page lands on `/chat/` and vue-router keeps that path
// verbatim. The tests drive this object to reproduce both shapes.
const routeMock = reactive({ path: '/' })

// SPEC-093: the stream is authorised by the session cookie the browser attaches
// to a `withCredentials` EventSource. Nothing identifying goes in the URL.
const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))

const authStub = makeAuthStub(userRef)

mockNuxtImport('useAuth', () => () => authStub)
mockNuxtImport('useRoute', () => () => routeMock)
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

// Nuxt 4.5 made `$fetch` an auto-import (from `#build/fetch.mjs`), so it is
// mocked like any other import; stubbing the global no longer reaches it.
mockNuxtImport('$fetch', () => fetchMock)

// Every constructed EventSource, so a test can count how many streams the
// composable actually opened and push events through them.
const streams: FakeEventSource[] = []

class FakeEventSource {
  url: string
  withCredentials: boolean
  closed = false
  // The composable treats a CLOSED handle as no connection at all (a tab the OS
  // froze can come back holding one), so the fake has to model it.
  readyState = 1
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
    this.readyState = 2
  }
}

// happy-dom ships no EventSource, so without this the composable's
// `new EventSource(...)` throws into its own catch and opens nothing. The
// assignment has to happen per-test: the Nuxt environment hands each test a
// fresh window.
function installFakeEventSource() {
  ;(window as unknown as Record<string, unknown>).EventSource = FakeEventSource
}

// What GET /chat/unread answers with. SPEC-061: this is the only thing that
// knows about messages which arrived while no tab was open.
let unreadResponse = { count: 0, has_unread: false }

function installFetchStub() {
  fetchMock.mockReset().mockImplementation((url: string) => {
    if (String(url).includes('/chat/unread')) {
      return Promise.resolve(unreadResponse)
    }
    if (String(url).includes('/chat/read')) {
      return Promise.resolve({ read_at: '2026-09-10T09:00:00+00:00' })
    }
    return Promise.resolve({})
  })
}

/** Calls the composable made against one of its endpoints. */
function callsTo(fragment: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes(fragment))
}

/** Drive `document.hidden`, which happy-dom leaves as a plain false. */
function setTabHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
}

const Host = defineComponent({
  setup() {
    return useNotifications()
  },
  template: '<div />'
})

describe('composables/useNotifications', () => {
  beforeEach(async () => {
    // A fresh session per test. Signing out is the ref reading null — since
    // SPEC-093 there is no event stream of auth states to replay, just the one
    // the server confirmed.
    userRef.value = null
    routeMock.path = '/'
    unreadResponse = { count: 0, has_unread: false }
    setTabHidden(false)
    toastAddMock.mockClear()
    streams.length = 0
    installFakeEventSource()
    installFetchStub()

    // Signing in is itself a reason to connect, so let that watcher settle and
    // then wipe the slate: a test asserting "one stream" or "no /chat/unread
    // call" is asserting about what IT provoked, not about the sign-in.
    userRef.value = { id: 'buyer-1' }
    await flushPromises()
    for (const stream of streams) stream.close()
    streams.length = 0
    fetchMock.mockClear()
    toastAddMock.mockClear()
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

      streams[0]!.emit({ type: 'new_message', message: 'Hi', source: 'admin', notify: true })
      expect(toastAddMock).toHaveBeenCalledTimes(1)

      first.vm.disconnect()
    })

    it('authorises the stream with the session cookie and puts nothing in the URL', async () => {
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()

      expect(streams[0]!.withCredentials).toBe(true)
      // A query string lands in proxy logs, browser history and the next
      // request's Referer. Nothing that authorises anything may be in one —
      // which is now trivially true, because there is nothing in it at all.
      expect(streams[0]!.url).toBe('http://localhost:8000/chat/notifications/stream')
      expect(streams[0]!.url).not.toContain('?')

      wrapper.vm.disconnect()
    })

    it('opens no stream when nobody is signed in', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.disconnect()
      streams.length = 0
      userRef.value = null

      await wrapper.vm.connect()
      await flushPromises()

      expect(streams).toHaveLength(0)
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

      streams[0]!.emit({ type: 'new_message', message: 'On my way', source: 'admin', notify: true })
      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({
        title: 'New message from Seller',
        description: 'On my way'
      }))

      streams[0]!.emit({ type: 'new_message', message: 'RM950 then', source: 'ai', notify: true })
      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({
        title: 'New message from Nego-Lah',
        description: 'RM950 then'
      }))

      wrapper.vm.disconnect()
    })

    it.each(['/chat', '/chat/'])('shows no toast while the chat page itself is open (%s)', async (path) => {
      // The user is already reading the conversation the message belongs to.
      // `/chat/` is what a hard load of the deployed SPA actually resolves to,
      // so an exact `=== '/chat'` guard let every message through there.
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()

      routeMock.path = path
      await flushPromises()

      streams[0]!.emit({ type: 'new_message', message: 'RM240 can?', source: 'ai', notify: true })

      expect(toastAddMock).not.toHaveBeenCalled()
      expect(wrapper.vm.hasUnread).toBe(false)
      expect(wrapper.vm.unreadCount).toBe(0)

      wrapper.vm.disconnect()
    })

    it('still toasts from a page that merely starts with the chat path', async () => {
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()

      routeMock.path = '/chatter'
      await flushPromises()

      streams[0]!.emit({ type: 'new_message', message: 'RM240 can?', source: 'ai', notify: true })

      expect(toastAddMock).toHaveBeenCalledTimes(1)

      wrapper.vm.disconnect()
    })

    it('clears the unread badge on arriving at the chat page, trailing slash or not', async () => {
      const wrapper = await mountSuspended(Host)
      wrapper.vm.hasUnread = true
      wrapper.vm.unreadCount = 3

      routeMock.path = '/chat/'
      await flushPromises()

      expect(wrapper.vm.hasUnread).toBe(false)
      expect(wrapper.vm.unreadCount).toBe(0)
    })
  })

  describe('unread state that outlives the tab (SPEC-061)', () => {
    it('shows the chip for messages that arrived while nothing was listening', async () => {
      // The whole point: no SSE event ever fires for these. They landed while
      // the buyer had no tab open, and the only record of them is the server's
      // watermark.
      unreadResponse = { count: 4, has_unread: true }
      const wrapper = await mountSuspended(Host)

      await wrapper.vm.connect()
      await flushPromises()

      expect(wrapper.vm.hasUnread).toBe(true)
      expect(wrapper.vm.unreadCount).toBe(4)

      wrapper.vm.disconnect()
    })

    it('does not hydrate a chip onto the chat page the buyer is already reading', async () => {
      unreadResponse = { count: 4, has_unread: true }
      routeMock.path = '/chat/'
      const wrapper = await mountSuspended(Host)

      await wrapper.vm.connect()
      await flushPromises()

      expect(callsTo('/chat/unread')).toHaveLength(0)
      expect(wrapper.vm.hasUnread).toBe(false)

      wrapper.vm.disconnect()
    })

    it('re-syncs when a backgrounded tab comes back', async () => {
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()

      unreadResponse = { count: 2, has_unread: true }
      setTabHidden(false)
      document.dispatchEvent(new Event('visibilitychange'))
      await flushPromises()

      expect(wrapper.vm.unreadCount).toBe(2)

      wrapper.vm.disconnect()
    })

    it('survives an unreadable count without breaking the header', async () => {
      fetchMock.mockImplementation((url: string) => {
        if (String(url).includes('/chat/unread')) return Promise.reject(new Error('500'))
        return Promise.resolve({ ticket: 'ticket-abc', expires_in: 30 })
      })
      const wrapper = await mountSuspended(Host)

      await wrapper.vm.connect()
      await flushPromises()

      expect(wrapper.vm.hasUnread).toBe(false)
      expect(wrapper.vm.unreadCount).toBe(0)

      wrapper.vm.disconnect()
    })

    it('stamps the watermark when the buyer lands on the chat page', async () => {
      const wrapper = await mountSuspended(Host)

      routeMock.path = '/chat/'
      await flushPromises()

      const [url, options] = callsTo('/chat/read')[0]!
      expect(url).toContain('/chat/read')
      expect(options.method).toBe('POST')
      expect(options.credentials).toBe('include')
      expect(options.headers).not.toHaveProperty('Authorization')

      wrapper.vm.disconnect()
    })

    it('stamps when a message is read live on the chat page', async () => {
      // Reading it as it lands is still reading it. Without this the watermark
      // stays where it was and the next cold load re-reports every message the
      // buyer already watched arrive.
      routeMock.path = '/chat'
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()
      const before = callsTo('/chat/read').length

      streams[0]!.emit({ type: 'new_message', message: 'RM240 can?', source: 'ai', notify: true })
      await flushPromises()

      expect(callsTo('/chat/read').length).toBe(before + 1)

      wrapper.vm.disconnect()
    })

    it('stamps on the way out of the conversation', async () => {
      // The buyer's own turn is the hole this closes: the agent's reply is
      // written after the arrival stamp and never comes through the
      // notification stream, so nothing moved the watermark past it. Chat,
      // walk away, reload — and the chip is back for a reply the buyer watched
      // stream in. Leaving the page covers everything that landed on it.
      routeMock.path = '/chat'
      const wrapper = await mountSuspended(Host)
      await flushPromises()
      const before = callsTo('/chat/read').length

      routeMock.path = '/'
      await flushPromises()

      expect(callsTo('/chat/read').length).toBe(before + 1)

      wrapper.vm.disconnect()
    })

    it('stamps once, however many components asked', async () => {
      // The badge is session state but the composable is per-caller, so a
      // navigation asks every mounted header to stamp at the same instant.
      routeMock.path = '/chat'
      const first = await mountSuspended(Host)
      const second = await mountSuspended(Host)
      await flushPromises()
      const before = callsTo('/chat/read').length

      routeMock.path = '/'
      await flushPromises()

      expect(callsTo('/chat/read').length).toBe(before + 1)

      first.vm.disconnect()
      second.vm.disconnect()
    })

    it('stamps on the way out even though the header unmounts with the layout', async () => {
      // `/chat` uses its own layout, so navigating back to the storefront
      // destroys the AppHeader that was watching the route and builds a new
      // one. Vue disposes a component's pre-flush watchers when it unmounts,
      // and the layout swap renders before the watcher would have run — so a
      // watcher owned by the header never sees the one transition it exists
      // for. The stream is already session-scoped for the same reason.
      routeMock.path = '/chat'
      const leaving = await mountSuspended(Host)
      await flushPromises()
      const before = callsTo('/chat/read').length

      routeMock.path = '/'
      leaving.unmount()
      const arriving = await mountSuspended(Host)
      await flushPromises()

      expect(callsTo('/chat/read').length).toBe(before + 1)

      arriving.vm.disconnect()
    })

    it('stamps when the conversation is backgrounded rather than left', async () => {
      // Same read, different exit: the tab goes to the background with the
      // reply on screen. Hydrating here would be the wrong move — the count it
      // reads back is the one this stamp is about to invalidate.
      routeMock.path = '/chat/'
      const wrapper = await mountSuspended(Host)
      await wrapper.vm.connect()
      await flushPromises()
      const before = callsTo('/chat/read').length
      const hydrated = callsTo('/chat/unread').length

      setTabHidden(true)
      document.dispatchEvent(new Event('visibilitychange'))
      await flushPromises()

      expect(callsTo('/chat/read').length).toBe(before + 1)
      expect(callsTo('/chat/unread').length).toBe(hydrated)

      // Leave the way we came in: the next test's route reset must not read as
      // a navigation off the chat page.
      routeMock.path = '/'
      await flushPromises()
      wrapper.vm.disconnect()
    })

    it('does not stamp when there was nothing to clear', async () => {
      const wrapper = await mountSuspended(Host)
      await flushPromises()

      wrapper.vm.clearUnread()
      await flushPromises()

      expect(callsTo('/chat/read')).toHaveLength(0)
    })

    it('does not stamp on the way out of a session', async () => {
      // Signing out clears the badge locally. Writing a read watermark for a
      // user who just left is both pointless and unauthenticated.
      userRef.value = { id: 'user-1' }
      const wrapper = await mountSuspended(Host)
      await flushPromises()
      wrapper.vm.hasUnread = true
      wrapper.vm.unreadCount = 3

      userRef.value = null
      await flushPromises()

      expect(wrapper.vm.hasUnread).toBe(false)
      expect(callsTo('/chat/read')).toHaveLength(0)
    })
  })

  it('exposes requestNotificationPermission function', async () => {
    const wrapper = await mountSuspended(Host)
    expect(typeof wrapper.vm.requestNotificationPermission).toBe('function')
    await expect(wrapper.vm.requestNotificationPermission()).resolves.toBeUndefined()
  })
})
