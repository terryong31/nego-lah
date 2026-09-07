import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import ChatPage from '~/pages/chat.vue'
import { useItemStore } from '~/stores/item'

// ---------------------------------------------------------------------------
// @ai-sdk/vue is a plain npm package (not a Nuxt auto-import), so it's mocked
// via vi.mock rather than mockNuxtImport. useChat is called exactly once by
// chat.vue's setup(), so we hand back the SAME pair of real Vue refs every
// time — tests mutate `messagesRef`/`statusRef` directly afterwards to
// simulate the SDK streaming a reply in. They must be genuine `ref()`s (not
// plain `{ value }` stand-ins) so the page's own `computed()`s (aiWorking,
// displayMessages, effectiveStatus, typingMessageId) react to changes made
// from the test, exactly like the real SDK's reactive state would.
// vi.mock's factory is hoisted above this file's imports, so anything it
// references must come through vi.hoisted — including `vue` itself, pulled
// in via `require` since the top-level `import` binding isn't available yet
// at hoist time.
// ---------------------------------------------------------------------------
const { messagesRef, statusRef, stopMock, sendMessageMock, useChatConfigHolder } = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const vue = require('vue')
  return {
    messagesRef: vue.ref([] as UIMessageLike[]),
    statusRef: vue.ref('ready' as string),
    stopMock: vi.fn(),
    sendMessageMock: vi.fn().mockResolvedValue(undefined),
    // Captures the config object chat.vue hands to useChat() — in particular
    // `transport`, the real (unmocked) DefaultChatTransport instance built
    // from the `headers`/`prepareSendMessagesRequest` closures in chat.vue.
    // Those closures are otherwise dead code under this mock (only the real
    // SDK would ever call them, when it actually sends a request), so a
    // couple of tests below pull them off the captured transport and call
    // them directly.
    useChatConfigHolder: { value: undefined as unknown }
  }
})

vi.mock('@ai-sdk/vue', () => ({
  useChat: (config: unknown) => {
    useChatConfigHolder.value = config
    return {
      messages: messagesRef,
      status: statusRef,
      stop: stopMock,
      sendMessage: sendMessageMock
    }
  }
}))

// Mock the `ai` package so we can capture the DefaultChatTransport options
// without needing a real HTTP connection. The mock class spreads all
// constructor options as instance properties so that
// `chatTransport().headers()` / `chatTransport().prepareSendMessagesRequest()`
// below still work. `onData` is NOT among these -- it's a top-level `useChat`
// option (see `useChatConfigHolder` above), not a transport one.
const { capturedTransportOptions } = vi.hoisted(() => ({
  capturedTransportOptions: { value: null as Record<string, unknown> | null }
}))

vi.mock('ai', async (importOriginal) => {
  const actual = await importOriginal<typeof import('ai')>()
  return {
    ...actual,
    DefaultChatTransport: class {
      [key: string]: unknown
      constructor(opts: Record<string, unknown>) {
        capturedTransportOptions.value = opts
        // Spread all options as direct properties so chatTransport().headers()
        // and chatTransport().prepareSendMessagesRequest() still work.
        Object.assign(this, opts)
      }
    }
  }
})

interface UIMessageLike {
  id: string
  role: 'user' | 'assistant' | 'system'
  parts: { type: string, text?: string }[]
}

interface ChatItem {
  item_id: string
  name: string
  price: number
  discounted_price?: number
  status: string
  images?: string
  translations?: Record<string, { name?: string, description?: string, condition?: string }>
}

// Shape of the <script setup> bindings this file reaches through wrapper.vm.
interface ChatVm {
  input: string
  hasMore: boolean
  loadingHistory: boolean
  loadingMore: boolean
  offset: number
  accessToken: string
  buyLoading: boolean
  aiStatusText: string
  aiWorking: boolean
  aiEnabled: boolean
  effectiveStatus: string
  shownText: string
  scroller: HTMLElement | null
  contextItem: ChatItem | null
  contextImage: string | null
  displayMessages: UIMessageLike[]
  send: (text: string) => Promise<void>
  loadMore: () => Promise<void>
  handleBuyNow: () => Promise<void>
  getMessageText: (message: Partial<UIMessageLike>) => string
  systemLabel: (message: Partial<UIMessageLike>) => string
  messageBlocks: (message: Partial<UIMessageLike>) => unknown[]
}

function vm(wrapper: Awaited<ReturnType<typeof mountSuspended>>) {
  return wrapper.vm as unknown as ChatVm
}

// The real DefaultChatTransport instance chat.vue built and handed to the
// (mocked) useChat() — see useChatConfigHolder above.
interface CapturedTransport {
  headers: () => Record<string, string>
  prepareSendMessagesRequest: (args: {
    messages: { parts?: { type: string, text?: string }[] }[]
    body: Record<string, unknown>
  }) => { body: Record<string, unknown> }
}
function chatTransport(): CapturedTransport {
  return (useChatConfigHolder.value as { transport: CapturedTransport }).transport
}

// Deferred promise helper for controlling exactly when an awaited call
// resolves, matching the pattern used elsewhere (e.g. items/index.test.ts).
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

// --- Nuxt auto-imports -------------------------------------------------
const callMock = vi.fn()
mockNuxtImport('useApi', () => () => ({ call: callMock }))

const toastAddMock = vi.fn()
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

const userRef: { value: { id: string } | null } = { value: null }
mockNuxtImport('useSupabaseUser', () => () => userRef)

const getSessionMock = vi.fn()
const onAuthStateChangeMock = vi.fn()
const signOutMock = vi.fn()
mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    getSession: getSessionMock,
    onAuthStateChange: onAuthStateChangeMock,
    signOut: signOutMock
  }
}))

const typingState = {
  remoteTyping: ref(false),
  join: vi.fn(),
  ping: vi.fn(),
  leave: vi.fn()
}
mockNuxtImport('useTypingChannel', () => () => typingState)

// `route.query.item_id` is read once at setup (contextItemId) — a real
// reactive object so we can flip it per test before mounting.
const routeStub = reactive<{ query: Record<string, string | undefined>, fullPath: string }>({ query: {}, fullPath: '/chat' })
mockNuxtImport('useRoute', () => () => routeStub)

// Hoisted: mockNuxtImport's factory is lifted above this file's top-level
// consts, and this one hands the mock back directly (rather than through a
// second arrow like the mocks above), so it must already exist by then.
const { navigateToMock } = vi.hoisted(() => ({ navigateToMock: vi.fn() }))
mockNuxtImport('navigateTo', () => navigateToMock)

let activeWrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

async function mountPage() {
  activeWrapper = await mountSuspended(ChatPage)
  await flushPromises()
  return activeWrapper
}

describe('pages/chat.vue', () => {
  beforeEach(() => {
    vi.useFakeTimers()

    messagesRef.value = []
    statusRef.value = 'ready'
    stopMock.mockReset()
    sendMessageMock.mockReset().mockResolvedValue(undefined)
    useChatConfigHolder.value = undefined

    callMock.mockReset().mockImplementation((path: string) => {
      if (path.startsWith('/chat/history/')) return Promise.resolve({ messages: [], next_offset: 0, has_more: false })
      return Promise.resolve({})
    })
    toastAddMock.mockReset()

    userRef.value = null
    getSessionMock.mockReset().mockResolvedValue({ data: { session: null } })
    onAuthStateChangeMock.mockReset()
    signOutMock.mockReset()

    typingState.join.mockReset()
    typingState.ping.mockReset()
    typingState.leave.mockReset()
    typingState.remoteTyping.value = false

    routeStub.query = {}
    routeStub.fullPath = '/chat'
    navigateToMock.mockReset()

    // SPEC-041: clear the shared item store between tests so a previous test's
    // cached item never bleeds into the next one.
    useItemStore().clear()
  })

  afterEach(() => {
    activeWrapper?.unmount()
    activeWrapper = undefined
    vi.useRealTimers()
  })

  describe('loadInitial / mapMessages', () => {
    it('does not fetch history and stops the loading skeleton when nobody is logged in', async () => {
      userRef.value = null
      getSessionMock.mockResolvedValue({ data: { session: null } })

      const wrapper = await mountPage()

      expect(callMock).not.toHaveBeenCalledWith(expect.stringContaining('/chat/history/'))
      expect(vm(wrapper).loadingHistory).toBe(false)
    })

    it('maps roles (human -> user, system role/source -> system, else -> assistant), falls back content -> message, drops blank/empty messages, and derives an id when missing', async () => {
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=0') {
          return Promise.resolve({
            messages: [
              { id: 'm1', role: 'human', content: 'Hello there' },
              { role: 'ai', message: 'Hi! (from the message field)' },
              { id: 'm3', role: 'assistant', content: '   ' }, // blank after trim -> dropped
              { id: 'm4', source: 'system', content: 'AI paused' },
              { id: 'm5', role: 'ai', content: '' } // empty -> dropped
            ],
            next_offset: 5,
            has_more: true
          })
        }
        return Promise.resolve({})
      })

      await mountPage()

      expect(messagesRef.value).toHaveLength(3)

      // No `source` on the record -> no data-source part is attached.
      expect(messagesRef.value[0]).toEqual({
        id: 'm1',
        role: 'user',
        parts: [{ type: 'text', text: 'Hello there' }]
      })

      // No `id` on the source record -> uid() derives one.
      expect(messagesRef.value[1]!.role).toBe('assistant')
      expect(messagesRef.value[1]!.parts[0]!.text).toBe('Hi! (from the message field)')
      expect(typeof messagesRef.value[1]!.id).toBe('string')
      expect(messagesRef.value[1]!.id.length).toBeGreaterThan(0)

      // SPEC-027: a stored `source` rides along so blocksFor can tell an AI
      // newline (a bubble boundary) from a human's (a line break).
      expect(messagesRef.value[2]).toEqual({
        id: 'm4',
        role: 'system',
        parts: [
          { type: 'text', text: 'AI paused' },
          { type: 'data-source', data: 'system' }
        ]
      })
    })

    it('seeds offset from next_offset and hasMore from has_more', async () => {
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=0') {
          return Promise.resolve({ messages: [{ id: 'm1', role: 'human', content: 'Hi' }], next_offset: 7, has_more: true })
        }
        return Promise.resolve({})
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).hasMore).toBe(true)
      expect(vm(wrapper).offset).toBe(7)
    })

    it('falls back to messages.length for offset when next_offset is absent', async () => {
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=0') {
          return Promise.resolve({ messages: [{ id: 'm1', role: 'human', content: 'Hi' }, { id: 'm2', role: 'ai', content: 'Yo' }] })
        }
        return Promise.resolve({})
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).offset).toBe(2)
      expect(vm(wrapper).hasMore).toBe(false)
    })

    it('swallows a failed history fetch (console.error) and still clears the loading flag', async () => {
      userRef.value = { id: 'user-1' }
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      callMock.mockImplementation((path: string) => {
        if (path.startsWith('/chat/history/')) return Promise.reject(new Error('network down'))
        return Promise.resolve({})
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).loadingHistory).toBe(false)
      expect(consoleErrorSpy).toHaveBeenCalledWith('Error loading chat history:', expect.any(Error))
    })
  })

  describe('currentUserId resolution', () => {
    it('prefers the reactive useSupabaseUser id and never needs a second getSession call for it', async () => {
      userRef.value = { id: 'reactive-uid' }
      callMock.mockImplementation((path: string) =>
        path === '/chat/history/reactive-uid?limit=20&offset=0' ? Promise.resolve({ messages: [] }) : Promise.resolve({}))

      await mountPage()

      expect(callMock).toHaveBeenCalledWith('/chat/history/reactive-uid?limit=20&offset=0')
    })

    it('falls back to session.user.id when the reactive user ref has no id', async () => {
      userRef.value = null
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'session-uid' }, access_token: 'tok' } } })
      callMock.mockImplementation((path: string) =>
        path === '/chat/history/session-uid?limit=20&offset=0' ? Promise.resolve({ messages: [] }) : Promise.resolve({}))

      await mountPage()

      expect(callMock).toHaveBeenCalledWith('/chat/history/session-uid?limit=20&offset=0')
    })
  })

  describe('loadMore pagination', () => {
    async function mountWithFirstPage() {
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=0') {
          return Promise.resolve({ messages: [{ id: 'recent', role: 'human', content: 'recent msg' }], next_offset: 20, has_more: true })
        }
        return Promise.resolve({})
      })
      return mountPage()
    }

    it('does nothing when there is nothing more to load', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage() // default mock: has_more false
      callMock.mockClear()

      await vm(wrapper).loadMore()

      expect(callMock).not.toHaveBeenCalled()
    })

    it('fetches the next page with the correct offset, prepends older messages, and updates offset/hasMore', async () => {
      const wrapper = await mountWithFirstPage()
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=20') {
          return Promise.resolve({ messages: [{ id: 'older', role: 'human', content: 'older msg' }], next_offset: 40, has_more: false })
        }
        return Promise.resolve({})
      })

      await vm(wrapper).loadMore()

      expect(callMock).toHaveBeenCalledWith('/chat/history/user-1?limit=20&offset=20')
      expect(messagesRef.value.map(m => m.id)).toEqual(['older', 'recent'])
      expect(vm(wrapper).offset).toBe(40)
      expect(vm(wrapper).hasMore).toBe(false)
    })

    it('preserves reading position: sets scrollTop to (newScrollHeight - prevScrollHeight) after prepending', async () => {
      const wrapper = await mountWithFirstPage()
      const scrollerEl = vm(wrapper).scroller!
      expect(scrollerEl).toBeTruthy()
      Object.defineProperty(scrollerEl, 'scrollHeight', { value: 500, configurable: true })

      const { promise, resolve } = deferred<{ messages: unknown[], next_offset: number, has_more: boolean }>()
      callMock.mockImplementationOnce(() => promise)

      const loadMorePromise = vm(wrapper).loadMore()
      await flushPromises() // let currentUserId resolve + prevHeight (500) get captured + the fetch fire

      // Simulate the DOM growing once the older messages are prepended.
      Object.defineProperty(scrollerEl, 'scrollHeight', { value: 800, configurable: true })
      resolve({ messages: [{ id: 'older', role: 'human', content: 'older msg' }], next_offset: 40, has_more: false })
      await loadMorePromise
      await nextTick()

      expect(scrollerEl.scrollTop).toBe(300)
    })

    it('does not start a second fetch while one is already in flight', async () => {
      const wrapper = await mountWithFirstPage()
      callMock.mockClear()
      const { promise, resolve } = deferred<{ messages: unknown[] }>()
      callMock.mockImplementationOnce(() => promise)

      const first = vm(wrapper).loadMore()
      await flushPromises()
      const second = vm(wrapper).loadMore()

      expect(callMock).toHaveBeenCalledTimes(1)
      resolve({ messages: [] })
      await Promise.all([first, second])
    })

    it('does nothing once the user is no longer resolvable (e.g. logged out) even if hasMore is still true', async () => {
      const wrapper = await mountWithFirstPage()
      callMock.mockClear()
      userRef.value = null
      getSessionMock.mockResolvedValue({ data: { session: null } })

      await vm(wrapper).loadMore()

      expect(callMock).not.toHaveBeenCalled()
    })

    it('shows a toast with the error message when the fetch fails, and stops the spinner', async () => {
      const wrapper = await mountWithFirstPage()
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=20') return Promise.reject(new Error('boom'))
        return Promise.resolve({})
      })

      await vm(wrapper).loadMore()

      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Failed to load older messages', description: 'boom', color: 'error' })
      expect(vm(wrapper).loadingMore).toBe(false)
    })

    it('falls back to a generic message when the rejection is not an Error instance', async () => {
      const wrapper = await mountWithFirstPage()
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=20') return Promise.reject('nope')
        return Promise.resolve({})
      })

      await vm(wrapper).loadMore()

      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Failed to load older messages', description: 'Something went wrong', color: 'error' })
    })
  })

  describe('onMounted wiring', () => {
    it('seeds accessToken from the initial session and subscribes to onAuthStateChange', async () => {
      userRef.value = { id: 'user-1' }
      getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok-1' } } })

      const wrapper = await mountPage()

      expect(vm(wrapper).accessToken).toBe('tok-1')
      expect(onAuthStateChangeMock).toHaveBeenCalledTimes(1)

      // The subscribed callback keeps accessToken in sync with future auth events.
      const onChange = onAuthStateChangeMock.mock.calls[0]![0] as (event: string, session: unknown) => void
      onChange('TOKEN_REFRESHED', { access_token: 'tok-2' })
      expect(vm(wrapper).accessToken).toBe('tok-2')

      onChange('SIGNED_OUT', null)
      expect(vm(wrapper).accessToken).toBe('')
    })

    it('joins the typing channel as the customer once the user id resolves', async () => {
      userRef.value = { id: 'user-1' }
      getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok-1' } } })

      await mountPage()

      expect(typingState.join).toHaveBeenCalledWith('user-1', expect.objectContaining({
        listenFor: 'seller',
        sendAs: 'customer',
        accessToken: 'tok-1',
        onMessage: expect.any(Function)
      }))
    })

    it('does not join the typing channel when nobody is logged in', async () => {
      userRef.value = null
      getSessionMock.mockResolvedValue({ data: { session: null } })

      await mountPage()

      expect(typingState.join).not.toHaveBeenCalled()
    })

    it('fetches the context item when route.query.item_id is present', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve({ item_id: 'item-1', name: 'Vintage Lamp', price: 45.5, status: 'available' })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(callMock).toHaveBeenCalledWith('/items/item-1')
      // contextItem is a computed from the store — it maps discountedPrice onto
      // discounted_price so callers don't care about the internal shape.
      expect(vm(wrapper).contextItem).toMatchObject({ item_id: 'item-1', name: 'Vintage Lamp', price: 45.5, status: 'available' })
    })

    it('does not fetch a context item when there is no item_id in the route', async () => {
      routeStub.query = {}
      userRef.value = { id: 'user-1' }

      const wrapper = await mountPage()

      expect(callMock).not.toHaveBeenCalledWith('/items/undefined')
      expect(vm(wrapper).contextItem).toBeNull()
    })

    it('silently swallows a failed context-item fetch, leaving contextItem null', async () => {
      routeStub.query = { item_id: 'gone' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/gone') return Promise.reject(new Error('404'))
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).contextItem).toBeNull()
    })

    it('shows the negotiated price, the struck-through listed price and the discount badge', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') {
          return Promise.resolve({ item_id: 'item-1', name: 'AirPods Max', price: 1199, discounted_price: 1000, status: 'available' })
        }
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(wrapper.text()).toContain('RM 1000.00')
      expect(wrapper.find('.line-through').text()).toContain('RM 1199.00')
      expect(wrapper.text()).toContain('-17%')
    })

    it('shows only the listed price while no offer has been negotiated', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve({ item_id: 'item-1', name: 'AirPods Max', price: 1199, status: 'available' })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(wrapper.text()).toContain('RM 1199.00')
      expect(wrapper.find('.line-through').exists()).toBe(false)
    })

    it('applies a negotiated discount in real-time via the onData SSE handler, so the header shows the discounted price immediately', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve({ item_id: 'item-1', name: 'AirPods Max', price: 1199, status: 'available' })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()
      expect(wrapper.text()).toContain('RM 1199.00')

      // Simulate the SSE data-discount frame arriving via useChat's own onData
      // callback -- the AI SDK invokes it once per data part received (never
      // as an array), and it's a top-level useChat option, not nested inside
      // DefaultChatTransport's options.
      const onData = (useChatConfigHolder.value as { onData?: (part: unknown) => void } | undefined)?.onData
      expect(onData, 'onData should be registered as a top-level useChat option').toBeDefined()
      onData?.({ type: 'data-discount', id: 'discount', data: { discounted_price: 1000 } })
      await nextTick()

      expect(vm(wrapper).contextItem?.discounted_price).toBe(1000)
      expect(wrapper.text()).toContain('RM 1000.00')
      expect(wrapper.text()).toContain('-17%')
    })

    it('does not call the items API again while a reply is streaming (store handles it via SSE)', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve({ item_id: 'item-1', name: 'AirPods Max', price: 1199, status: 'available' })
        return Promise.resolve({ messages: [] })
      })

      await mountPage()
      callMock.mockClear()

      statusRef.value = 'submitted'
      await nextTick()
      statusRef.value = 'streaming'
      await flushPromises()

      expect(callMock).not.toHaveBeenCalledWith('/items/item-1')
    })
  })

  describe('realtime onMessage (seller typing-channel broadcast)', () => {
    async function mountAndGetOnMessage() {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()
      const onMessage = typingState.join.mock.calls[0]![1].onMessage as (payload: unknown) => void
      return { wrapper, onMessage }
    }

    it('pushes a well-formed payload directly into the message list', async () => {
      const { onMessage } = await mountAndGetOnMessage()
      const before = messagesRef.value.length

      onMessage({ role: 'assistant', content: 'Seller: I can do RM45' })
      await nextTick()

      expect(messagesRef.value).toHaveLength(before + 1)
      const injected = messagesRef.value.at(-1)!
      expect(injected.role).toBe('assistant')
      expect(injected.parts).toEqual([{ type: 'text', text: 'Seller: I can do RM45' }])
      expect(typeof injected.id).toBe('string')
    })

    it('maps role/source "system" to a system-role message', async () => {
      const { onMessage } = await mountAndGetOnMessage()

      onMessage({ role: 'system', content: 'Terry has joined the chat' })
      await nextTick()

      expect(messagesRef.value.at(-1)!.role).toBe('system')

      onMessage({ role: 'assistant', source: 'system', content: 'Terry has left the chat' })
      await nextTick()

      expect(messagesRef.value.at(-1)!.role).toBe('system')
    })

    it('drops payloads with no content, and never throws on a null/undefined payload', async () => {
      const { onMessage } = await mountAndGetOnMessage()
      const before = messagesRef.value.length

      expect(() => onMessage(null)).not.toThrow()
      expect(() => onMessage(undefined)).not.toThrow()
      onMessage({ role: 'assistant' })

      expect(messagesRef.value).toHaveLength(before)
    })
  })

  describe('send()', () => {
    it('does nothing for blank/whitespace-only text', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()
      getSessionMock.mockClear()

      await vm(wrapper).send('    ')

      expect(getSessionMock).not.toHaveBeenCalled()
      expect(sendMessageMock).not.toHaveBeenCalled()
    })

    it('via the prompt form: refreshes the access token, clears the textarea, and forwards the trimmed text', async () => {
      userRef.value = { id: 'user-1' }
      getSessionMock.mockResolvedValueOnce({ data: { session: { access_token: 'initial-token' } } })
      const wrapper = await mountPage()

      getSessionMock.mockResolvedValueOnce({ data: { session: { access_token: 'fresh-token' } } })
      const textarea = wrapper.find('textarea')
      await textarea.setValue('  Will you take RM50?  ')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(getSessionMock).toHaveBeenCalled()
      expect(vm(wrapper).accessToken).toBe('fresh-token')
      expect(sendMessageMock).toHaveBeenCalledWith({ text: 'Will you take RM50?' })
      expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('')
    })

    it('bounces to login carrying the chat URL when the session has lapsed, instead of posting an empty Bearer token', async () => {
      userRef.value = { id: 'user-1' }
      routeStub.query = { item_id: 'item-9' }
      routeStub.fullPath = '/chat?item_id=item-9'
      const wrapper = await mountPage()
      getSessionMock.mockClear().mockResolvedValue({ data: { session: null } })

      await vm(wrapper).send('Can you do RM50?')

      expect(sendMessageMock).not.toHaveBeenCalled()
      expect(signOutMock).toHaveBeenCalledTimes(1)
      expect(navigateToMock).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/chat?item_id=item-9' }
      })
      expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ color: 'warning' }))
    })

    it('keeps the typed message in the box when the send is refused for a lapsed session', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()
      getSessionMock.mockClear().mockResolvedValue({ data: { session: null } })
      vm(wrapper).input = 'Can you do RM50?'

      await vm(wrapper).send('Can you do RM50?')

      expect(vm(wrapper).input).toBe('Can you do RM50?')
    })

    it('sends normally (no bounce) when the session is still alive', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()
      getSessionMock.mockClear().mockResolvedValue({ data: { session: { access_token: 'still-good' } } })

      await vm(wrapper).send('Deal?')

      expect(navigateToMock).not.toHaveBeenCalled()
      expect(sendMessageMock).toHaveBeenCalledWith({ text: 'Deal?' })
    })

    it('directly: always fetches a fresh token even if one is already cached (the stale-token 401 guard)', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()
      getSessionMock.mockClear().mockResolvedValue({ data: { session: { access_token: 'brand-new' } } })

      await vm(wrapper).send('Deal?')

      expect(getSessionMock).toHaveBeenCalledTimes(1)
      expect(vm(wrapper).accessToken).toBe('brand-new')
      expect(sendMessageMock).toHaveBeenCalledWith({ text: 'Deal?' })
    })
  })

  // The `headers`/`prepareSendMessagesRequest` callbacks are handed straight
  // to `new DefaultChatTransport({...})` inside useChat()'s config. Because
  // useChat() itself is mocked (see the top of this file), the real SDK never
  // calls them — so we grab the actual transport instance chat.vue built via
  // useChatConfigHolder and invoke its callbacks directly.
  describe('useChat transport config (headers / prepareSendMessagesRequest)', () => {
    it('headers() returns a Bearer header built from the current accessToken', async () => {
      userRef.value = { id: 'user-1' }
      getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok-abc' } } })
      await mountPage()

      expect(chatTransport().headers()).toEqual({ Authorization: 'Bearer tok-abc' })
    })

    it('headers() falls back to an empty-token Bearer header when there is no session', async () => {
      userRef.value = null
      getSessionMock.mockResolvedValue({ data: { session: null } })
      await mountPage()

      expect(chatTransport().headers()).toEqual({ Authorization: 'Bearer ' })
    })

    it('prepareSendMessagesRequest joins the last message\'s text parts (ignoring non-text parts) and merges user_id/item_id into the body', async () => {
      routeStub.query = { item_id: 'item-9' }
      userRef.value = { id: 'user-42' }
      await mountPage()

      const result = chatTransport().prepareSendMessagesRequest({
        messages: [
          { parts: [{ type: 'text', text: 'Hello ' }] },
          { parts: [{ type: 'text', text: 'Hello ' }, { type: 'tool-call' }, { type: 'text', text: 'World' }] }
        ],
        body: { existing: true }
      })

      expect(result).toEqual({
        body: {
          existing: true,
          message: 'Hello World',
          user_id: 'user-42',
          item_id: 'item-9'
        }
      })
    })

    it('prepareSendMessagesRequest defaults to an empty message and null item_id when there is no last message / no item context', async () => {
      routeStub.query = {}
      userRef.value = { id: 'user-1' }
      await mountPage()

      const result = chatTransport().prepareSendMessagesRequest({ messages: [], body: {} })

      expect(result).toEqual({
        body: { message: '', user_id: 'user-1', item_id: null }
      })
    })
  })

  describe('getMessageText', () => {
    it('joins all text parts and strips [[STATUS:...]] markers, including multiple markers', async () => {
      const wrapper = await mountPage()

      const text = vm(wrapper).getMessageText({
        role: 'assistant',
        parts: [
          { type: 'text', text: '[[STATUS:Searching…]]' },
          { type: 'text', text: 'Here is my offer: RM45' },
          { type: 'text', text: '[[STATUS:Done]]' }
        ]
      })

      expect(text).toBe('Here is my offer: RM45')
    })

    it('returns an empty string for a message with no parts', async () => {
      const wrapper = await mountPage()
      expect(vm(wrapper).getMessageText({ role: 'assistant' })).toBe('')
    })

    it('ignores non-text parts', async () => {
      const wrapper = await mountPage()
      const text = vm(wrapper).getMessageText({
        role: 'assistant',
        // @ts-expect-error deliberately mixing part types like the SDK would
        parts: [{ type: 'tool-call' }, { type: 'text', text: 'hello' }]
      })
      expect(text).toBe('hello')
    })
  })

  describe('systemLabel', () => {
    it('trims surrounding dashes/whitespace from a system notice', async () => {
      const wrapper = await mountPage()
      const label = vm(wrapper).systemLabel({ role: 'system', parts: [{ type: 'text', text: '--- Terry has joined the chat ---' }] })
      expect(label).toBe('Terry has joined the chat')
    })
  })

  describe('blocksFor', () => {
    // SPEC-027: a newline means whatever the author's input method made it mean.
    const aiMsg = (text: string): Partial<UIMessageLike> => ({ id: 'not-typing', role: 'assistant', parts: [{ type: 'text', text }] })
    const buyerMsg = (text: string): Partial<UIMessageLike> => ({ id: 'not-typing', role: 'user', parts: [{ type: 'text', text }] })
    const sellerMsg = (text: string): Partial<UIMessageLike> => ({
      id: 'not-typing',
      role: 'assistant',
      parts: [{ type: 'text', text }, { type: 'data-source', data: 'admin' }]
    })

    it('gives each of the AI\'s blank-line-separated blocks its own bubble', async () => {
      const wrapper = await mountPage()
      const blocks = vm(wrapper).blocksFor(aiMsg('First line\n\n  Second line  \n'))
      expect(blocks).toEqual([
        { type: 'text', text: 'First line' },
        { type: 'text', text: 'Second line' }
      ])
    })

    it('keeps the AI\'s single line breaks inside one bubble, so an address stays whole', async () => {
      const wrapper = await mountPage()
      const blocks = vm(wrapper).blocksFor(aiMsg('Shipping to:\nTerry Ong\n12 Jalan Ampang, KL'))
      expect(blocks).toEqual([
        { type: 'text', text: 'Shipping to:\nTerry Ong\n12 Jalan Ampang, KL' }
      ])
    })

    it('keeps a buyer\'s Shift+Enter message in one bubble with newlines intact', async () => {
      const wrapper = await mountPage()
      const blocks = vm(wrapper).blocksFor(buyerMsg('First line\n\n  Second line  \n'))
      expect(blocks).toEqual([{ type: 'text', text: 'First line\n\n  Second line' }])
    })

    it('keeps a seller takeover message in one bubble — also a human at a keyboard', async () => {
      const wrapper = await mountPage()
      const blocks = vm(wrapper).blocksFor(sellerMsg('Ships from KL\nUsually 2-3 days'))
      expect(blocks).toEqual([{ type: 'text', text: 'Ships from KL\nUsually 2-3 days' }])
    })

    it('renders a complete markdown payment link as a "pay" block', async () => {
      const wrapper = await mountPage()
      const blocks = vm(wrapper).blocksFor(aiMsg('[Pay RM50 Now](https://buy.stripe.com/abc123)'))
      expect(blocks).toEqual([{ type: 'pay', label: 'Pay RM50 Now', url: 'https://buy.stripe.com/abc123' }])
    })

    it('renders a still-streaming payment link fragment as a "pending" placeholder', async () => {
      const wrapper = await mountPage()
      const blocks = vm(wrapper).blocksFor(aiMsg('Here you go: [Pay Now](http'))
      expect(blocks).toEqual([
        { type: 'text', text: 'Here you go:' },
        { type: 'pending' }
      ])
    })
  })

  describe('contextImage', () => {
    it('picks the first URL out of the item\'s images JSON array', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') {
          return Promise.resolve({ item_id: 'item-1', name: 'Lamp', price: 20, status: 'available', images: JSON.stringify(['https://img/1.png', 'https://img/2.png']) })
        }
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).contextImage).toBe('https://img/1.png')
    })

    it('returns null when images is invalid JSON', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve({ item_id: 'item-1', name: 'Lamp', price: 20, status: 'available', images: 'not-json' })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).contextImage).toBeNull()
    })

    it('returns null when images is an empty array or absent', async () => {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve({ item_id: 'item-1', name: 'Lamp', price: 20, status: 'available', images: '[]' })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()

      expect(vm(wrapper).contextImage).toBeNull()
    })
  })

  describe('handleBuyNow', () => {
    async function mountWithContextItem(overrides: Partial<ChatItem> = {}) {
      routeStub.query = { item_id: 'item-1' }
      userRef.value = { id: 'user-1' }
      const item = { item_id: 'item-1', name: 'Vintage Lamp', price: 45, status: 'available', ...overrides }
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve(item)
        return Promise.resolve({ messages: [] })
      })
      return mountPage()
    }

    it('does nothing when there is no context item', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage() // no item_id in route -> contextItem stays null
      callMock.mockClear()

      await vm(wrapper).handleBuyNow()

      expect(callMock).not.toHaveBeenCalledWith('/payment/checkout', expect.anything())
      expect(vm(wrapper).buyLoading).toBe(false)
    })

    it('on success, redirects the browser to the returned checkout_url', async () => {
      const wrapper = await mountWithContextItem()
      callMock.mockImplementation((path: string, opts?: Record<string, unknown>) => {
        if (path === '/payment/checkout') {
          expect(opts).toEqual({ method: 'POST', body: { item_id: 'item-1', user_id: 'user-1' } })
          return Promise.resolve({ checkout_url: 'https://checkout.stripe.com/session-abc' })
        }
        return Promise.resolve({ messages: [] })
      })

      // jsdom/happy-dom throws "Not implemented: navigation" if we actually
      // assign location.href, so stub it out to observe the intent instead.
      const hrefSetter = vi.fn()
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, set href(v: string) { hrefSetter(v) } }
      })

      await vm(wrapper).handleBuyNow()

      expect(hrefSetter).toHaveBeenCalledWith('https://checkout.stripe.com/session-abc')
      expect(vm(wrapper).buyLoading).toBe(false)
    })

    it('shows a "Checkout failed" toast when the response has no checkout_url', async () => {
      const wrapper = await mountWithContextItem()
      callMock.mockImplementation((path: string) => {
        if (path === '/payment/checkout') return Promise.resolve({})
        return Promise.resolve({ messages: [] })
      })

      await vm(wrapper).handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Checkout failed', description: 'No checkout URL returned', color: 'error' })
      expect(vm(wrapper).buyLoading).toBe(false)
    })

    it('shows the Error\'s message when the checkout call rejects with an Error', async () => {
      const wrapper = await mountWithContextItem()
      callMock.mockImplementation((path: string) => {
        if (path === '/payment/checkout') return Promise.reject(new Error('Card declined'))
        return Promise.resolve({ messages: [] })
      })

      await vm(wrapper).handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Checkout failed', description: 'Card declined', color: 'error' })
    })

    it('falls back to a generic message when the rejection is not an Error instance (e.g. a raw 401/403 response object)', async () => {
      const wrapper = await mountWithContextItem()
      callMock.mockImplementation((path: string) => {
        if (path === '/payment/checkout') return Promise.reject({ statusCode: 401, data: { detail: 'Unauthorized' } })
        return Promise.resolve({ messages: [] })
      })

      await vm(wrapper).handleBuyNow()

      // Note: handleBuyNow has no login/redirect branch of its own — chat.vue
      // never calls navigateTo('/login') here. That redirect only happens
      // inside the real useApi() 401 interceptor (mocked away in this suite),
      // so from handleBuyNow's own point of view every rejection — 401, 403,
      // 409 "already sold", or otherwise — that isn't a real Error instance
      // just falls through to this generic fallback toast.
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Checkout failed', description: 'Unable to start transaction', color: 'error' })
    })

    it('a 409 "item already sold" style rejection is not special-cased — same generic fallback toast', async () => {
      const wrapper = await mountWithContextItem()
      callMock.mockImplementation((path: string) => {
        if (path === '/payment/checkout') return Promise.reject({ statusCode: 409, data: { detail: 'Item already sold' } })
        return Promise.resolve({ messages: [] })
      })

      await vm(wrapper).handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Checkout failed', description: 'Unable to start transaction', color: 'error' })
    })

    it('the "Buy" button in the item header calls handleBuyNow', async () => {
      const wrapper = await mountWithContextItem()
      const { promise, resolve } = deferred<{ checkout_url?: string }>()
      callMock.mockImplementation((path: string) => (path === '/payment/checkout' ? promise : Promise.resolve({ messages: [] })))

      const buyButton = wrapper.findAll('button').find(b => b.text() === 'Buy Now')
      expect(buyButton).toBeTruthy()
      await buyButton!.trigger('click')

      expect(vm(wrapper).buyLoading).toBe(true)
      resolve({ checkout_url: undefined })
      await flushPromises()
      expect(vm(wrapper).buyLoading).toBe(false)
    })

    it('shows a "Sold" badge instead of the Buy button once the item is sold', async () => {
      const wrapper = await mountWithContextItem({ status: 'sold' })

      expect(wrapper.findAll('button').find(b => b.text() === 'Buy Now')).toBeUndefined()
      expect(wrapper.text()).toContain('Sold')
    })

    it('pins the listing under its translation for the active locale', async () => {
      const wrapper = await mountWithContextItem({
        name: 'Apple AirPods Max Space Gray with Box',
        translations: { en: { name: 'AirPods Max — Full Set, Like New' } }
      })

      expect(wrapper.text()).toContain('AirPods Max — Full Set, Like New')
      expect(wrapper.text()).not.toContain('Apple AirPods Max Space Gray with Box')
    })

    it('falls back to the seller\'s own wording when that locale has no translation', async () => {
      const wrapper = await mountWithContextItem({
        name: 'Apple AirPods Max Space Gray with Box',
        translations: { ms: { name: 'Tidak berkaitan' } }
      })

      expect(wrapper.text()).toContain('Apple AirPods Max Space Gray with Box')
    })
  })

  describe('client-side typewriter effect', () => {
    // These drive the typewriter through the real send() path, which now
    // refuses to send (and bounces to login) without a live session — the
    // suite-wide default is a logged-out one.
    beforeEach(() => {
      getSessionMock.mockResolvedValue({ data: { session: { access_token: 'live-token' } } })
    })

    it('reveals the assistant reply one character at a time at CHAR_RATE (50/s = 20ms/char) while streaming', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      const textarea = wrapper.find('textarea')
      await textarea.setValue('Offer?')
      await wrapper.find('form').trigger('submit')
      await flushPromises() // send() resolves getSession + starts the interval

      // Simulate the SDK streaming the assistant's reply in.
      messagesRef.value = [
        { id: 'u1', role: 'user', parts: [{ type: 'text', text: 'Offer?' }] },
        { id: 'a1', role: 'assistant', parts: [{ type: 'text', text: 'Sure' }] }
      ]
      statusRef.value = 'streaming'
      await nextTick()

      await vi.advanceTimersByTimeAsync(20)
      expect(vm(wrapper).shownText).toBe('S')

      await vi.advanceTimersByTimeAsync(20)
      expect(vm(wrapper).shownText).toBe('Su')

      await vi.advanceTimersByTimeAsync(40)
      expect(vm(wrapper).shownText).toBe('Sure')

      // Stream ends once fully revealed -> stopTyping() clears the interval
      // and resets shownText (the bubble falls back to plain getMessageText
      // rendering once typingId no longer matches).
      statusRef.value = 'ready'
      await vi.advanceTimersByTimeAsync(20)
      expect(vm(wrapper).shownText).toBe('')
    })

    it('only reveals the clean text — [[STATUS:...]] markers never appear in shownText', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      await wrapper.find('textarea').setValue('Deal?')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      messagesRef.value = [
        { id: 'a1', role: 'assistant', parts: [{ type: 'text', text: '[[STATUS:Searching…]]Sure thing' }] }
      ]
      statusRef.value = 'streaming'
      await nextTick()

      await vi.advanceTimersByTimeAsync(20 * 10)
      expect(vm(wrapper).shownText).toBe('Sure thing')
    })

    it('does not advance shownText once the target text is fully caught up mid-stream', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      await wrapper.find('textarea').setValue('Deal?')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      messagesRef.value = [{ id: 'a1', role: 'assistant', parts: [{ type: 'text', text: 'Hi' }] }]
      statusRef.value = 'streaming'
      await nextTick()

      await vi.advanceTimersByTimeAsync(20 * 5)
      expect(vm(wrapper).shownText).toBe('Hi')
      // Still streaming (more text may arrive) — shownText stays put rather
      // than resetting, since typeTick only stops once the status settles.
      expect(vm(wrapper).shownText).toBe('Hi')
    })

    it('typeTick stops (and clears) the interval once ticking with no assistant message yet and the stream not active', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      await wrapper.find('textarea').setValue('Offer?')
      await wrapper.find('form').trigger('submit')
      await flushPromises() // send() resolves + startTyping() begins the interval; the mock never
      // pushes anything into messagesRef, so at this point messages is still [] and status is 'ready'.

      // First tick: no last message at all, and status is neither 'streaming'
      // nor 'submitted' -> typeTick's early-return branch calls stopTyping(),
      // clearing the interval outright.
      await vi.advanceTimersByTimeAsync(20)
      expect(vm(wrapper).shownText).toBe('')

      // Prove the interval was actually torn down (not just idle): even once
      // an assistant message shows up and the stream goes live, nothing
      // resumes typing because startTyping() was never called again.
      messagesRef.value = [{ id: 'a1', role: 'assistant', parts: [{ type: 'text', text: 'Sure' }] }]
      statusRef.value = 'streaming'
      await nextTick()
      await vi.advanceTimersByTimeAsync(1000)

      expect(vm(wrapper).shownText).toBe('')
    })

    it('typeTick leaves the interval running (no stopTyping) when the last message is not the assistant\'s yet but the stream is already active', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      await wrapper.find('textarea').setValue('Offer?')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      // The user's own echoed message lands first, with the stream already
      // marked active -> typeTick's inner stopTyping guard is false, so it
      // just returns without tearing down the interval.
      messagesRef.value = [{ id: 'u1', role: 'user', parts: [{ type: 'text', text: 'Offer?' }] }]
      statusRef.value = 'streaming'
      await nextTick()
      await vi.advanceTimersByTimeAsync(20)
      expect(vm(wrapper).shownText).toBe('')

      // The interval is still alive: once the assistant reply appears, typing resumes normally.
      messagesRef.value = [...messagesRef.value, { id: 'a1', role: 'assistant', parts: [{ type: 'text', text: 'Sure' }] }]
      await nextTick()
      await vi.advanceTimersByTimeAsync(20)
      expect(vm(wrapper).shownText).toBe('S')
    })
  })

  describe('reactive computeds driven by the (mocked) SDK state', () => {
    it('aiWorking is true only while streaming with an empty-parts assistant reply, and displayMessages blanks that bubble', async () => {
      const wrapper = await mountPage()

      messagesRef.value = [
        { id: 'u1', role: 'user', parts: [{ type: 'text', text: 'Offer?' }] },
        { id: 'a1', role: 'assistant', parts: [] }
      ]
      statusRef.value = 'streaming'
      await nextTick()

      expect(vm(wrapper).aiWorking).toBe(true)
      expect(vm(wrapper).displayMessages.at(-1)!.parts).toEqual([])

      messagesRef.value = [
        messagesRef.value[0]!,
        { id: 'a1', role: 'assistant', parts: [{ type: 'text', text: 'Sure thing' }] }
      ]
      await nextTick()

      expect(vm(wrapper).aiWorking).toBe(false)
      expect(vm(wrapper).displayMessages.at(-1)!.parts[0]!.text).toBe('Sure thing')
    })

    it('never shows the AI working indicator once the seller has taken over', async () => {
      // chat_settings.ai_enabled = false: the backend records the buyer's
      // message and closes the stream without replying, so "Cooking…" would
      // promise an answer that never arrives.
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/settings/user-1') return Promise.resolve({ ai_enabled: false })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()
      await flushPromises()
      expect(vm(wrapper).aiEnabled).toBe(false)

      messagesRef.value = [
        { id: 'u1', role: 'user', parts: [{ type: 'text', text: 'Hello?' }] },
        { id: 'a1', role: 'assistant', parts: [] }
      ]
      statusRef.value = 'streaming'
      await nextTick()

      expect(vm(wrapper).aiWorking).toBe(false)
      expect(vm(wrapper).effectiveStatus).toBe('ready')
    })

    it('still surfaces the seller typing indicator while the AI is paused', async () => {
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/settings/user-1') return Promise.resolve({ ai_enabled: false })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()
      await flushPromises()

      typingState.remoteTyping.value = true
      await nextTick()
      expect(vm(wrapper).effectiveStatus).toBe('submitted')

      typingState.remoteTyping.value = false
      await nextTick()
    })

    it('re-reads the AI setting when a takeover separator arrives mid-conversation', async () => {
      userRef.value = { id: 'user-1' }
      let aiOn = true
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/settings/user-1') return Promise.resolve({ ai_enabled: aiOn })
        return Promise.resolve({ messages: [] })
      })

      const wrapper = await mountPage()
      await flushPromises()
      expect(vm(wrapper).aiEnabled).toBe(true)

      aiOn = false
      const onMessage = typingState.join.mock.calls[0]![1].onMessage as (p: unknown) => void
      onMessage({ role: 'system', source: 'system', content: '--- Terry has joined the chat ---' })
      await flushPromises()

      expect(vm(wrapper).aiEnabled).toBe(false)
    })

    it('effectiveStatus is forced to "submitted" while the seller is typing, independent of the AI stream status', async () => {
      const wrapper = await mountPage()
      statusRef.value = 'ready'

      typingState.remoteTyping.value = true
      await nextTick()
      expect(vm(wrapper).effectiveStatus).toBe('submitted')

      typingState.remoteTyping.value = false
      await nextTick()
      expect(vm(wrapper).effectiveStatus).toBe('ready')
    })

    it('extracts the latest [[STATUS:...]] marker from a streaming assistant message into aiStatusText', async () => {
      const wrapper = await mountPage()

      messagesRef.value = [{ id: 'a1', role: 'assistant', parts: [{ type: 'text', text: '[[STATUS:Searching the market…]]' }] }]
      await nextTick()
      expect(vm(wrapper).aiStatusText).toBe('Searching the market…')

      messagesRef.value = [{ id: 'a1', role: 'assistant', parts: [{ type: 'text', text: '[[STATUS:Searching the market…]][[STATUS:Drafting a counter-offer…]]Almost there' }] }]
      await nextTick()
      expect(vm(wrapper).aiStatusText).toBe('Drafting a counter-offer…')
    })

    // aiStatusText holds ONLY the agent's own [[STATUS:…]] text, which is
    // English-only from the backend. It resets to empty (not to a hardcoded
    // English word) so the indicator falls back to the translated
    // `chat.thinking` key between tool calls.
    it('resets aiStatusText to empty whenever status transitions to "submitted"', async () => {
      const wrapper = await mountPage()

      messagesRef.value = [{ id: 'a1', role: 'assistant', parts: [{ type: 'text', text: '[[STATUS:Searching the market…]]' }] }]
      await nextTick()
      expect(vm(wrapper).aiStatusText).toBe('Searching the market…')

      statusRef.value = 'submitted'
      await nextTick()
      expect(vm(wrapper).aiStatusText).toBe('')
    })

    it('starts with no hardcoded status so the first frame shows the translated label', async () => {
      const wrapper = await mountPage()
      expect(vm(wrapper).aiStatusText).toBe('')
    })
  })

  describe('work-process indicator', () => {
    function findIndicator(wrapper: Awaited<ReturnType<typeof mountPage>>) {
      return wrapper.findAllComponents({ name: 'UChatTool' })[0]
        ?? wrapper.findAllComponents({ name: 'ChatTool' })[0]
    }

    it('shows the animated brand mark instead of Nuxt UI\'s default spinner', async () => {
      // The page renders its empty state (not <UChatMessages>) until there is
      // at least one message, so the #indicator slot needs a populated thread.
      messagesRef.value = [{ id: 'u1', role: 'user', parts: [{ type: 'text', text: 'How much?' }] }]
      statusRef.value = 'submitted'
      const wrapper = await mountPage()
      await nextTick()

      const indicator = findIndicator(wrapper)
      expect(indicator).toBeTruthy()

      // `loading` would make ChatTool resolve appConfig.ui.icons.loading and
      // stamp `animate-spin` on the leading icon (see .nuxt/ui/chat-tool.ts),
      // overriding both the brand mark and its hop.
      expect(indicator!.props('loading')).toBe(false)
      expect(indicator!.props('icon')).toBe('i-nego-mark')
      expect(indicator!.props('ui')?.leadingIcon).toContain('animate-brand-hop')
      expect(indicator!.props('ui')?.leadingIcon).toContain('text-default')
    })

    it('keeps the seller-typing state on its own icon, unanimated', async () => {
      messagesRef.value = [{ id: 'u1', role: 'user', parts: [{ type: 'text', text: 'How much?' }] }]
      typingState.remoteTyping.value = true
      statusRef.value = 'ready'
      const wrapper = await mountPage()
      await nextTick()

      const indicator = findIndicator(wrapper)
      expect(indicator!.props('icon')).toBe('i-lucide-store')
      expect(indicator!.props('ui')?.leadingIcon ?? '').not.toContain('animate-brand-hop')
    })
  })

  describe('empty/loading render states', () => {
    it('shows loading skeletons while history is being fetched', async () => {
      userRef.value = { id: 'user-1' }
      const { promise } = deferred<{ messages: unknown[] }>()
      callMock.mockImplementation((path: string) => (path.startsWith('/chat/history/') ? promise : Promise.resolve({})))

      const wrapper = await mountPage()

      expect(wrapper.findAllComponents({ name: 'USkeleton' }).length).toBeGreaterThan(0)
    })

    it('shows the empty state once history has loaded with no messages', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage() // default: empty history

      expect(wrapper.text()).toContain('Send a message to start negotiating')
    })

    it('shows a "Load older messages" button only when hasMore is true', async () => {
      userRef.value = { id: 'user-1' }
      callMock.mockImplementation((path: string) => {
        if (path === '/chat/history/user-1?limit=20&offset=0') {
          return Promise.resolve({ messages: [{ id: 'm1', role: 'human', content: 'hi' }], next_offset: 20, has_more: true })
        }
        return Promise.resolve({})
      })

      const wrapper = await mountPage()

      expect(wrapper.text()).toContain('Load older messages')
    })
  })

  // -------------------------------------------------------------------------
  // SPEC-043 workstream E — the buyer can tell the three waits apart
  // -------------------------------------------------------------------------
  describe('cooldown and slow-turn feedback', () => {
    function onDataHandler() {
      const handler = (useChatConfigHolder.value as { onData?: (part: unknown) => void } | undefined)?.onData
      expect(handler, 'onData should be registered as a top-level useChat option').toBeDefined()
      return handler!
    }

    it('turns a 429 into a visible countdown and gates the composer', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(
          JSON.stringify({ detail: { code: 'chat_cooldown', retryAfterSeconds: 12 } }),
          { status: 429, headers: { 'Retry-After': '12', 'Content-Type': 'application/json' } }
        )
      )

      try {
        const transportFetch = chatTransport().fetch
        const replacement = await transportFetch('/chat/stream', { method: 'POST' })

        // The SDK is handed a well-formed, empty stream rather than an error,
        // so the composer settles instead of hanging mid-send.
        expect(replacement.status).toBe(200)
        expect(await replacement.text()).toContain('[DONE]')
      } finally {
        fetchSpy.mockRestore()
      }

      await nextTick()

      expect(vm(wrapper).cooldown.isCoolingDown.value).toBe(true)
      expect(vm(wrapper).cooldown.secondsLeft.value).toBe(12)
      expect(wrapper.text()).toContain('You can send another message in 12s')
    })

    it('falls back to Retry-After when the body has been rewritten by a proxy', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('<html>Too Many Requests</html>', {
          status: 429,
          headers: { 'Retry-After': '7' }
        })
      )

      try {
        await chatTransport().fetch('/chat/stream', { method: 'POST' })
      } finally {
        fetchSpy.mockRestore()
      }

      await nextTick()
      expect(vm(wrapper).cooldown.secondsLeft.value).toBe(7)
    })

    it('releases the composer on its own once the countdown runs out', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      vm(wrapper).cooldown.start(3)
      await nextTick()
      expect(vm(wrapper).cooldown.isCoolingDown.value).toBe(true)

      await vi.advanceTimersByTimeAsync(3000)
      await nextTick()

      expect(vm(wrapper).cooldown.isCoolingDown.value).toBe(false)
      expect(wrapper.text()).not.toContain('You can send another message in')
    })

    it('warns before the wall without blocking anything', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      onDataHandler()({ type: 'data-cooldown-warning', id: 'cooldown-warning', data: { remaining: 2 } })
      await nextTick()

      expect(wrapper.text()).toContain('2 more before a short pause')
      expect(vm(wrapper).cooldown.isCoolingDown.value).toBe(false)
    })

    it('offers a retry for a timed-out turn instead of blaming the buyer', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      onDataHandler()({ type: 'data-turn-timeout', id: 'turn-timeout', data: { partial: false } })
      await nextTick()

      expect(wrapper.text()).toContain('That took longer than expected')
      expect(wrapper.text()).toContain('Try again')
      // A slow turn is the system's problem, not the buyer's — nothing gates.
      expect(vm(wrapper).cooldown.isCoolingDown.value).toBe(false)
    })

    it('resends the last message when the buyer retries a timed-out turn', async () => {
      userRef.value = { id: 'user-1' }
      getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok', user: { id: 'user-1' } } } })
      const wrapper = await mountPage()

      await vm(wrapper).send('is 800 ok?')
      await flushPromises()
      sendMessageMock.mockClear()

      onDataHandler()({ type: 'data-turn-timeout', id: 'turn-timeout', data: { partial: false } })
      await nextTick()

      await vm(wrapper).retryLastTurn()
      await flushPromises()

      expect(sendMessageMock).toHaveBeenCalledWith({ text: 'is 800 ok?' })
    })

    it('changes only the indicator wording when a turn runs long', async () => {
      userRef.value = { id: 'user-1' }
      const wrapper = await mountPage()

      statusRef.value = 'streaming'
      await nextTick()
      expect(vm(wrapper).indicatorText).toBe('Cooking…')

      await vi.advanceTimersByTimeAsync(8000)
      await nextTick()

      expect(vm(wrapper).indicatorText).toContain('taking a little longer')
      // Still just a label — the buyer is never blocked for the system's slowness.
      expect(vm(wrapper).cooldown.isCoolingDown.value).toBe(false)
    })
  })
})
