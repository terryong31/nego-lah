/**
 * The route watcher has to outlive the header that registered it.
 *
 * `/chat` has its own layout, so leaving it destroys the AppHeader watching the
 * route and builds a new one. Vue disposes a component's pre-flush watchers on
 * unmount, and the layout swap renders first — so a watcher owned by the header
 * never sees the one transition it exists for. The stream and the auth listener
 * are already session-scoped for exactly this reason.
 *
 * This lives in its own file deliberately: the main suite leaves every Host it
 * mounts alive, and their watchers would answer for the one under test.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useNotifications } from '../../app/composables/useNotifications'

const userRef = ref<Record<string, unknown> | null>(null)
const toastAddMock = vi.fn()
// Cloudflare Pages serves the SPA at the directory form of a route, so a hard
// load of the chat page lands on `/chat/` and vue-router keeps that path
// verbatim. The tests drive this object to reproduce both shapes.
const routeMock = reactive({ path: '/' })

// SPEC-056 #6: the stream is authorised by a short-lived ticket minted over a
// header-authenticated POST, never by the access token in the URL.
const fetchMock = vi.fn()

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useRoute', () => () => routeMock)
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

// What GET /chat/unread answers with. SPEC-061: this is the only thing that
// knows about messages which arrived while no tab was open.
const unreadResponse = { count: 0, has_unread: false }

// $fetch is a genuine global (ofetch/Nitro), not a Nuxt auto-import, so stub the
// global directly — same approach as tests/composables/useApi.test.ts.
function installFetchStub() {
  fetchMock.mockReset().mockImplementation((url: string) => {
    if (String(url).includes('/chat/notifications/ticket')) {
      return Promise.resolve({ ticket: 'ticket-abc', expires_in: 30 })
    }
    if (String(url).includes('/chat/unread')) {
      return Promise.resolve(unreadResponse)
    }
    if (String(url).includes('/chat/read')) {
      return Promise.resolve({ read_at: '2026-09-10T09:00:00+00:00' })
    }
    return Promise.resolve({})
  })
  ;(globalThis as unknown as Record<string, unknown>).$fetch = fetchMock
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

describe('useNotifications route scope', () => {
  beforeEach(() => {
    userRef.value = null
    routeMock.path = '/'
    setTabHidden(false)
    toastAddMock.mockClear()
    streams.length = 0
    installFakeEventSource()
    installFetchStub()
  })

  it('stamps the conversation read when the header unmounts with the layout', async () => {
    routeMock.path = '/chat'
    const leaving = await mountSuspended(Host)
    await flushPromises()
    expect(callsTo('/chat/read')).toHaveLength(1)

    // The layout swap: the route changes and the old header is torn down
    // before the scheduler ever reaches its watcher.
    routeMock.path = '/'
    leaving.unmount()
    const arriving = await mountSuspended(Host)
    await flushPromises()

    expect(callsTo('/chat/read')).toHaveLength(2)

    arriving.unmount()
  })
})
