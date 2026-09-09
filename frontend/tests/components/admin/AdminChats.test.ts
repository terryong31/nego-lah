import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { ref } from 'vue'
import AdminChats from '~/components/admin/AdminChats.vue'

interface ChatSummary {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  last_message: string
  last_role: string
  unread: boolean
}

function makeChat(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return {
    user_id: 'u1',
    display_name: 'Alice',
    avatar_url: null,
    message_count: 3,
    last_message: 'Hi there',
    last_role: 'user',
    unread: false,
    ...overrides
  }
}

// Deferred promise helper for controlling exactly when an awaited call resolves.
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const callMock = vi.fn()
mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))

const toastAdd = vi.fn()
mockNuxtImport('useToast', () => () => ({ add: toastAdd }))

const typingState = {
  remoteTyping: ref(false),
  join: vi.fn(),
  ping: vi.fn(),
  leave: vi.fn()
}
mockNuxtImport('useTypingChannel', () => () => typingState)

describe('components/admin/AdminChats.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAdd.mockReset()
    typingState.join.mockReset()
    typingState.ping.mockReset()
    typingState.leave.mockReset()
    typingState.remoteTyping.value = false

    // useAsyncData caches by key ('admin-chats') on the shared nuxtApp instance
    // that backs every test in this file, so without clearing it, only the very
    // first test's mount would ever actually invoke the fetcher.
    clearNuxtData('admin-chats')

    // Default happy-path routing: list endpoint returns nothing until a test
    // overrides it; message + send endpoints succeed.
    callMock.mockImplementation((path: string) => {
      if (path === '/chats') return Promise.resolve([])
      if (path.startsWith('/chats/') && path.includes('/message')) return Promise.resolve({ ok: true })
      if (path.startsWith('/chats/')) return Promise.resolve({ user_id: 'u1', messages: [] })
      return Promise.resolve(null)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a loading skeleton for the conversation list while the initial fetch is pending', async () => {
    const { promise, resolve } = deferred<ChatSummary[]>()
    callMock.mockImplementationOnce(() => promise)

    const wrapper = await mountSuspended(AdminChats)
    expect(wrapper.findAllComponents({ name: 'USkeleton' }).length).toBeGreaterThan(0)
    expect(wrapper.text()).not.toContain('No conversations yet.')

    resolve([makeChat()])
    await flushPromises()

    expect(wrapper.findAllComponents({ name: 'USkeleton' }).length).toBe(0)
    expect(wrapper.text()).toContain('Alice')
  })

  it('shows the empty state when there are no conversations at all', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.text()).toContain('No conversations yet.')
  })

  it('renders the chat list with display name, last message, and message count', async () => {
    callMock.mockImplementationOnce(() =>
      Promise.resolve([
        makeChat({ user_id: 'u1', display_name: 'Alice', last_message: 'Hello!', message_count: 5 }),
        makeChat({ user_id: 'u2', display_name: 'Bob', last_message: '', message_count: 0 })
      ])
    )

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('Hello!')
    expect(wrapper.text()).toContain('5 messages')
    expect(wrapper.text()).toContain('Bob')
    // Falls back to an em dash when there is no last message.
    expect(wrapper.text()).toContain('—')
  })

  it('filters the list by unread / read / all', async () => {
    callMock.mockImplementationOnce(() =>
      Promise.resolve([
        makeChat({ user_id: 'u1', display_name: 'Alice', unread: true }),
        makeChat({ user_id: 'u2', display_name: 'Bob', unread: false })
      ])
    )

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    // 'All' is selected by default.
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('Bob')

    const [allTab, unreadTab, readTab] = wrapper.findAll('button').filter(b =>
      ['All', 'Unread', 'Read'].includes(b.text())
    )

    await unreadTab!.trigger('click')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).not.toContain('Bob')

    await readTab!.trigger('click')
    expect(wrapper.text()).not.toContain('Alice')
    expect(wrapper.text()).toContain('Bob')

    await allTab!.trigger('click')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('Bob')
  })

  it('shows a filter-specific empty message when the filter excludes every conversation', async () => {
    callMock.mockImplementationOnce(() =>
      Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice', unread: false })])
    )

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const unreadTab = wrapper.findAll('button').find(b => b.text() === 'Unread')
    await unreadTab!.trigger('click')

    expect(wrapper.text()).toContain('No conversations match.')
  })

  it('shows the placeholder pane until a conversation is selected', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat()]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.text()).toContain('Select a conversation to view and reply.')
  })

  it('open(): clicking a conversation loads its messages and joins the typing channel', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const { promise: msgPromise, resolve: resolveMsgs } = deferred<{ user_id: string, messages: unknown[] }>()
    callMock.mockImplementationOnce(() => msgPromise)

    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')

    // Typing channel joined immediately, before the messages fetch resolves.
    expect(typingState.join).toHaveBeenCalledWith('u1', expect.objectContaining({
      listenFor: 'customer',
      sendAs: 'seller',
      onMessage: expect.any(Function)
    }))
    expect(callMock).toHaveBeenCalledWith('/chats/u1?limit=100')

    // While loading, a skeleton stands in for the thread and the empty-state pane is gone.
    expect(wrapper.findAllComponents({ name: 'USkeleton' }).length).toBeGreaterThan(0)
    expect(wrapper.text()).not.toContain('Select a conversation to view and reply.')

    resolveMsgs({
      user_id: 'u1',
      messages: [
        { role: 'user', content: 'Hello' },
        { role: 'ai', content: 'Hi, how can I help?' }
      ]
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Hello')
    expect(wrapper.text()).toContain('Hi, how can I help?')
  })

  it('open(): shows a toast when loading messages fails', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.reject({ data: { detail: 'boom' } })
    )

    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Failed to load chat',
      description: 'boom',
      color: 'error'
    }))
  })

  it('a "new_message" broadcast from the typing channel appends a message and re-renders', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const joinCall = typingState.join.mock.calls[0]!
    const onMessage = joinCall[1].onMessage as (payload: unknown) => void

    onMessage({ role: 'ai', content: 'Live update!', source: 'ai' })
    await flushPromises()

    expect(wrapper.text()).toContain('Live update!')
  })

  it('a "new_message" broadcast with no content is ignored', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const joinCall = typingState.join.mock.calls[0]!
    const onMessage = joinCall[1].onMessage as (payload: unknown) => void

    expect(() => onMessage(null)).not.toThrow()
    expect(() => onMessage({ role: 'ai' })).not.toThrow()
  })

  it('shows the "Customer is typing" indicator only while a conversation is open and remoteTyping is true', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.text()).not.toContain('Customer is typing')

    typingState.remoteTyping.value = true
    await flushPromises()
    // No conversation open yet, so the indicator must not show.
    expect(wrapper.text()).not.toContain('Customer is typing')

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Customer is typing')

    typingState.remoteTyping.value = false
    await flushPromises()
    expect(wrapper.text()).not.toContain('Customer is typing')
  })

  it('offers no close control on desktop, where the list never leaves the screen', async () => {
    // The split view keeps the conversation list beside the thread, so closing
    // is only meaningful on mobile — where the Back button covers it (see the
    // single-pane test below).
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Select a conversation to view and reply.')

    const header = wrapper.find('header')
    expect(header.find('[aria-label="Close conversation"]').exists()).toBe(false)
    // The only control left in the header is the AI toggle.
    expect(header.findAll('button')).toHaveLength(1)
  })

  it('gives the AI badge and its toggle a matching size, with the toggle solid', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const badge = wrapper.findComponent({ name: 'UBadge' })
    const toggle = wrapper.findAllComponents({ name: 'UButton' })
      .find(b => ['Take over', 'Resume AI'].includes(b.text()))!

    // Badge `md` and button `xs` share px-2 py-1 text-xs, so they line up.
    expect(badge.props('size')).toBe('md')
    expect(toggle.props('size')).toBe('xs')
    expect(toggle.props('variant')).toBe('solid')
  })

  it('send(): optimistically appends the outgoing message and clears the input', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const { promise: sendPromise, resolve: resolveSend } = deferred<{ ok: boolean }>()
    callMock.mockImplementationOnce(() => sendPromise)

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Sure, that works for me')
    await wrapper.find('form').trigger('submit')

    expect(callMock).toHaveBeenCalledWith('/chats/u1/message', {
      method: 'POST',
      body: { message: 'Sure, that works for me' }
    })

    // Message list only updates optimistically once the POST resolves.
    expect(wrapper.text()).not.toContain('Sure, that works for me')

    resolveSend({ ok: true })
    await flushPromises()

    expect(wrapper.text()).toContain('Sure, that works for me')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('send(): renders the seller\'s own message once, not twice when the broadcast echoes back', async () => {
    // The backend broadcasts every admin message to chat:{user_id}, and this
    // console is subscribed to that same channel — so its own send comes back
    // as a `new_message` event on top of the optimistic append.
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ ok: true }))
    const textarea = wrapper.find('textarea')
    await textarea.setValue('This is a duplicated message')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const onMessage = typingState.join.mock.calls[0]![1].onMessage as (payload: unknown) => void
    onMessage({ role: 'ai', content: 'This is a duplicated message', source: 'admin' })
    await flushPromises()

    const copies = wrapper.text().split('This is a duplicated message').length - 1
    expect(copies).toBe(1)
  })

  it('send(): does nothing when the reply is blank/whitespace or no conversation is selected', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    // No conversation selected — the reply box isn't even rendered yet.
    expect(wrapper.find('textarea').exists()).toBe(false)

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    callMock.mockClear()
    const textarea = wrapper.find('textarea')
    await textarea.setValue('   ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(callMock).not.toHaveBeenCalled()
  })

  it('send(): shows a toast when sending fails, and leaves the draft text in place', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.reject({ message: 'Network error' }))

    const textarea = wrapper.find('textarea')
    await textarea.setValue('This will fail')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Send failed',
      description: 'Network error',
      color: 'error'
    }))

    // The draft is preserved (reply.value is only cleared on the success path)
    // rather than lost on failure. Confirmed behaviourally: submitting again
    // without retyping still sends the same text — a cleared draft would hit
    // send()'s early-return guard (`if (!text ...) return`) and produce no
    // second call at all.
    callMock.mockImplementationOnce(() => Promise.resolve({ ok: true }))
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(callMock).toHaveBeenLastCalledWith('/chats/u1/message', {
      method: 'POST',
      body: { message: 'This will fail' }
    })
  })

  it('typing in the reply box pings the typing channel', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('h')

    expect(typingState.ping).toHaveBeenCalled()
  })

  it('renders a plain-text message body as plain text', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({ user_id: 'u1', messages: [{ role: 'ai', content: 'Just a plain reply, no links here.' }] })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Just a plain reply, no links here.')
    expect(wrapper.text()).not.toContain('Deal agreed')
    expect(wrapper.text()).not.toContain('Preparing payment link')
  })

  it('renders a "[label](https://...)" markdown link as a payment CTA block', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'ai', content: '[Pay now](https://pay.example.com/session/abc123)' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Deal agreed')
    // No RM amount in this label, so the card keeps the Stripe line and the
    // agent's own wording on the button.
    expect(wrapper.text()).toContain('Complete your purchase securely via Stripe')
    const payLink = wrapper.findAll('a').find(a => a.text() === 'Pay now')
    expect(payLink).toBeTruthy()
    expect(payLink!.attributes('href')).toBe('https://pay.example.com/session/abc123')
  })

  it('shows the agreed amount as the payment card\'s headline when the label carries one', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'ai', content: '[Pay RM1000 Now](https://pay.example.com/session/abc123)' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('RM 1000.00')
    expect(wrapper.text()).not.toContain('Pay RM1000 Now')
  })

  it('renders a bare "](http" fragment with no completed markdown link as a pending payment placeholder', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    // Simulates a payment link still streaming in — the closing paren/URL isn't
    // complete yet, so the PAY_LINK regex doesn't match, but the tell-tale
    // "](http" fragment is already present.
    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'ai', content: 'Here you go: [Pay now](http' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Preparing payment link…')
    expect(wrapper.text()).not.toContain('Deal agreed')
  })

  // SPEC-027: the console must render the thread the same shape the buyer sees.
  it('splits an AI message on its blank lines, one bubble per block', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'ai', source: 'ai', content: 'First line\n\nSecond line' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const bubbles = wrapper.findAll('div.rounded-2xl')
    expect(bubbles.length).toBe(2)
    expect(bubbles[0]!.text()).toBe('First line')
    expect(bubbles[1]!.text()).toBe('Second line')
  })

  it('keeps an AI message\'s single line breaks in one bubble, so an address stays whole', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'ai', source: 'ai', content: 'Shipping to:\nTerry Ong\n12 Jalan Ampang, KL' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const bubbles = wrapper.findAll('div.rounded-2xl')
    expect(bubbles.length).toBe(1)
    expect(bubbles[0]!.text()).toBe('Shipping to:\nTerry Ong\n12 Jalan Ampang, KL')
  })

  it('keeps a seller-typed message in a single bubble with whitespace-pre-wrap', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    // source: 'admin' -> the seller pressed Shift+Enter, so this is one message.
    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'ai', source: 'admin', content: 'First line\n\nSecond line' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const bubbles = wrapper.findAll('div.rounded-2xl')
    expect(bubbles.length).toBe(1)
    expect(bubbles[0]!.text()).toBe('First line\n\nSecond line')
    expect(bubbles[0]!.element.className).toContain('whitespace-pre-wrap')
  })

  it('renders a system-role message as a centred separator with trimmed dash/whitespace label', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [{ role: 'system', content: '  -- AI replies paused --  ' }]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.findComponent({ name: 'USeparator' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('AI replies paused')
  })

  it('places the buyer on the left and admin-sourced messages on the right (seller side) alongside AI messages', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [
          { role: 'user', content: 'Buyer message' },
          { role: 'ai', content: 'Admin message', source: 'admin' }
        ]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Buyer message')
    expect(wrapper.text()).toContain('Admin message')

    // The buyer's bubble uses the "incoming" style and sits in a left-aligned
    // row; the seller's (admin-sourced) bubble uses the "outgoing" style and
    // sits in a right-aligned row. Bubbles are matched via their unique
    // "rounded-2xl" leaf class — several ancestor <div>s share the same
    // textContent, so a plain text match would otherwise hit the wrong node.
    const buyerBubble = wrapper.findAll('div.rounded-2xl').find(d => d.text() === 'Buyer message')!.element
    const sellerBubble = wrapper.findAll('div.rounded-2xl').find(d => d.text() === 'Admin message')!.element
    expect(buyerBubble.className).toContain('bg-elevated')
    expect(buyerBubble.parentElement?.className).toContain('items-start')
    expect(sellerBubble.className).toContain('bg-secondary')
    expect(sellerBubble.parentElement?.className).toContain('items-end')
  })

  it('refresh button re-fetches the conversation list', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u2', display_name: 'Zoe' })]))
    const refreshButton = wrapper.findAllComponents({ name: 'UButton' }).find(b => b.props('icon') === 'i-lucide-refresh-cw')!
    await refreshButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Zoe')
    expect(wrapper.text()).not.toContain('Alice')
  })

  it('toggles AI mode (HITL takeover) for the selected user', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice', ai_enabled: true })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('AI Active')
    const takeOverBtn = wrapper.findAll('button').find(b => b.text() === 'Take over')!
    expect(takeOverBtn).toBeDefined()

    callMock.mockImplementationOnce(() => Promise.resolve({ message: 'AI disabled for user' }))
    await takeOverBtn.trigger('click')
    await flushPromises()

    expect(callMock).toHaveBeenCalledWith('/users/u1/ai', {
      method: 'PUT',
      body: { ai_enabled: false }
    })
    expect(wrapper.text()).toContain('AI Paused')
  })

  it('re-syncs the AI badge from the backend on any system notice, not by matching its text (SPEC-046 #39)', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice', ai_enabled: true })]))
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('AI Active')

    // The agent's own transfer notice — wording the old substring matcher never recognised.
    callMock.mockImplementation((path: string) => {
      if (path === '/users/u1/ai') return Promise.resolve({ user_id: 'u1', ai_enabled: false })
      if (path === '/chats') return Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice', ai_enabled: false })])
      return Promise.resolve(null)
    })

    const onMessage = typingState.join.mock.calls[0]![1].onMessage as (payload: unknown) => void
    onMessage({ role: 'system', content: '--- The AI has transferred the chat to Terry (human seller) who will take over shortly ---', source: 'system' })
    await flushPromises()

    expect(callMock).toHaveBeenCalledWith('/users/u1/ai')
    expect(wrapper.text()).toContain('AI Paused')
  })

  it('opening a paused conversation shows "AI Paused" and a HITL badge in the list (SPEC-046 #39)', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([
      makeChat({ user_id: 'u1', display_name: 'Alice', ai_enabled: false })
    ]))
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.text()).toContain('HITL')

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('AI Paused')
    expect(wrapper.findAll('button').some(b => b.text() === 'Resume AI')).toBe(true)
  })

  it('search filters the conversation list by name and last message (SPEC-046 #42)', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([
      makeChat({ user_id: 'u1', display_name: 'Alice', last_message: 'is the lamp still available' }),
      makeChat({ user_id: 'u2', display_name: 'Bob', last_message: 'thanks!' })
    ]))
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const input = wrapper.findAllComponents({ name: 'UInput' })[0]!
    await input.vm.$emit('update:modelValue', 'alice')
    await flushPromises()
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).not.toContain('Bob')

    await input.vm.$emit('update:modelValue', 'lamp')
    await flushPromises()
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).not.toContain('Bob')

    await input.vm.$emit('update:modelValue', 'nothing-matches-this')
    await flushPromises()
    expect(wrapper.text()).toContain('No conversations match.')
  })

  it('sorts the list by most messages when that sort is chosen (SPEC-046 #42)', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([
      makeChat({ user_id: 'u1', display_name: 'Alice', message_count: 2 }),
      makeChat({ user_id: 'u2', display_name: 'Bob', message_count: 9 })
    ]))
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const select = wrapper.findAllComponents({ name: 'USelect' })[0]!
    await select.vm.$emit('update:modelValue', 'messages')
    await flushPromises()

    const names = wrapper.findAll('button')
      .map(b => b.text())
      .filter(txt => txt.includes('Alice') || txt.includes('Bob'))
    expect(names[0]).toContain('Bob')
    expect(names[1]).toContain('Alice')
  })

  it('passes paid prop to ChatPayCard when messages indicate completed deal', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() =>
      Promise.resolve({
        user_id: 'u1',
        messages: [
          { role: 'ai', content: '[Pay RM1000 Now](https://pay.example.com/session/abc123)' },
          { role: 'system', content: 'Payment received! Order completed.' }
        ]
      })
    )
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    const payCard = wrapper.findComponent({ name: 'ChatPayCard' })
    expect(payCard.exists()).toBe(true)
    expect(payCard.props('paid')).toBe(true)
  })

  it('switches to single-pane navigation on mobile and navigates back with the Back button', async () => {
    window.innerWidth = 375
    window.dispatchEvent(new Event('resize'))

    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ user_id: 'u1', display_name: 'Alice' })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    // On mobile, initially only conversation list is shown
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).not.toContain('Select a conversation to view and reply.')

    callMock.mockImplementationOnce(() => Promise.resolve({ user_id: 'u1', messages: [{ role: 'user', content: 'Hello mobile' }] }))
    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    // In thread view on mobile: shows messages and Back button
    expect(wrapper.text()).toContain('Hello mobile')
    const backBtn = wrapper.findAll('button').find(b => b.text() === 'Back')!
    expect(backBtn).toBeDefined()

    // Clicking Back button returns to conversation list
    await backBtn.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).not.toContain('Hello mobile')

    // Reset window width back to desktop
    window.innerWidth = 1024
    window.dispatchEvent(new Event('resize'))
  })
})
