/**
 * The notification stream has to come back on its own.
 *
 * Every failure path in `openStream` used to end in a bare `return`: the ticket
 * mint failing, `new EventSource` throwing, no session yet. None of them
 * scheduled a retry, so a single transient failure — a backend restart, a token
 * that expired between the check and the call — left the buyer with no stream
 * for the rest of the page's life. No toast, no chip, nothing until a reload,
 * while `GET /chat/unread` kept answering correctly for anyone who refreshed.
 *
 * Its own file: these drive fake timers and module-scoped backoff state, and the
 * main suite leaves every Host it mounts alive.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
// Captured so a test can fire real Supabase auth events at the composable.
let authCallback: ((event: string, session: unknown) => void) | null = null

mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    getSession: () => Promise.resolve({ data: { session: { access_token: 'jwt-token' } } }),
    onAuthStateChange: (cb: (event: string, session: unknown) => void) => {
      authCallback = cb
      return { data: { subscription: { unsubscribe: () => {} } } }
    }
  }
}))

// Every constructed EventSource, so a test can count how many streams the
// composable actually opened and push events through them.
const streams: FakeEventSource[] = []

class FakeEventSource {
  static readonly CLOSED = 2
  url: string
  readyState = 1
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

describe('useNotifications stream recovery', () => {
  beforeEach(() => {
    userRef.value = null
    routeMock.path = '/'
    setTabHidden(false)
    toastAddMock.mockClear()
    streams.length = 0
    installFakeEventSource()
    installFetchStub()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // First in the file on purpose: the liveness interval is created on the first
  // composable call, so it has to be created under this test's clock.
  it('notices a stream that ended without an error event', async () => {
    // The server saw the subscription end; the client never heard about it. A
    // connection can go away without `onerror` ever firing — the tab was
    // frozen, the socket was closed under it, the error was swallowed — and
    // nothing event-driven can fire on an event that never arrives. So
    // something has to actually look.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const wrapper = await mountSuspended(Host)
    userRef.value = { sub: 'user-4' }
    await vi.advanceTimersByTimeAsync(50)
    expect(streams).toHaveLength(1)

    streams[0]!.readyState = FakeEventSource.CLOSED // no error, no close()
    await vi.advanceTimersByTimeAsync(20_000)

    expect(streams, 'a dead stream nobody checks stays dead').toHaveLength(2)

    wrapper.vm.disconnect()
    wrapper.unmount()
  })

  it('comes back after a ticket mint that failed', async () => {
    // The dev API restarting under `--reload` is enough: the stream drops, the
    // retry lands while the server is still booting, and the mint fails.
    const wrapper = await mountSuspended(Host)

    vi.useFakeTimers()
    fetchMock.mockRejectedValueOnce(new Error('502 while the API restarts'))
    userRef.value = { sub: 'user-1' }
    await vi.advanceTimersByTimeAsync(0)
    expect(streams, 'the mint failed, so nothing opened yet').toHaveLength(0)

    await vi.advanceTimersByTimeAsync(5_000)

    expect(streams, 'a stream that never retries is a chip that never arrives').toHaveLength(1)

    wrapper.vm.disconnect()
    wrapper.unmount()
  })

  it('replaces a handle that closed without ever erroring', async () => {
    // A tab the OS froze and thawed comes back with a dead `EventSource` and no
    // error event to announce it. `connect()` guards on the handle being
    // non-null, so that dead object was enough to refuse every reconnect for
    // the rest of the session.
    const wrapper = await mountSuspended(Host)
    userRef.value = { sub: 'user-3' }
    await flushPromises()
    expect(streams).toHaveLength(1)

    streams[0]!.readyState = FakeEventSource.CLOSED
    await wrapper.vm.connect()
    await flushPromises()

    expect(streams).toHaveLength(2)

    wrapper.vm.disconnect()
    wrapper.unmount()
  })

  it('keeps the stream through an auth event whose session is momentarily null', async () => {
    // Supabase emits plenty of events with no session attached — a refresh in
    // flight, a re-read on navigation. Treating every one of them as "the user
    // is gone" tore down a healthy stream at exactly the moment the buyer was
    // navigating INTO the conversation, which is the moment before the agent
    // answers them. Measured on the live stack: the stream died ~4s before each
    // send and the reply, 2s later, had nowhere to go.
    const wrapper = await mountSuspended(Host)
    userRef.value = { sub: 'user-5' }
    await flushPromises()
    expect(streams).toHaveLength(1)

    authCallback?.('TOKEN_REFRESHED', null)
    await flushPromises()

    expect(streams[0]!.closed, 'a null session is not a sign-out').toBe(false)

    wrapper.vm.disconnect()
    wrapper.unmount()
  })

  it('closes the stream when the buyer actually signs out', async () => {
    const wrapper = await mountSuspended(Host)
    userRef.value = { sub: 'user-6' }
    await flushPromises()
    expect(streams).toHaveLength(1)

    authCallback?.('SIGNED_OUT', null)
    await flushPromises()

    expect(streams[0]!.closed).toBe(true)

    wrapper.unmount()
  })

  it('gives up once the buyer has signed out', async () => {
    const wrapper = await mountSuspended(Host)

    vi.useFakeTimers()
    fetchMock.mockRejectedValueOnce(new Error('502'))
    userRef.value = { sub: 'user-2' }
    await vi.advanceTimersByTimeAsync(0)
    userRef.value = null
    await vi.advanceTimersByTimeAsync(30_000)

    expect(streams).toHaveLength(0)

    wrapper.unmount()
  })
})

// ---------------------------------------------------------------------------
// SPEC-085 — the stream was gated on a claim that does not exist
//
// `useSupabaseUser()` holds the JWT payload from `getClaims()`, where the id is
// `sub`. Every guard in this composable read `user.value?.id`, which is
// `undefined` there — so `connect()` returned early every time and the stream
// never opened in production. These tests mocked the user as `{ id }`, which is
// exactly why they passed against it.
// ---------------------------------------------------------------------------

describe('useNotifications: the user id comes from the `sub` claim (SPEC-085)', () => {
  beforeEach(() => {
    userRef.value = null
    routeMock.path = '/'
    setTabHidden(false)
    streams.length = 0
    installFakeEventSource()
    installFetchStub()
  })

  it('opens a stream for a claims-shaped user, which carries `sub` and no `id`', async () => {
    const wrapper = await mountSuspended(Host)
    userRef.value = { sub: 'claims-user' }
    await flushPromises()

    expect(streams, 'a user with only `sub` must still be recognised').toHaveLength(1)

    wrapper.vm.disconnect()
    wrapper.unmount()
  })

  it('still opens nothing when signed out', async () => {
    const wrapper = await mountSuspended(Host)
    userRef.value = null
    await flushPromises()

    expect(streams).toHaveLength(0)

    wrapper.unmount()
  })
})
