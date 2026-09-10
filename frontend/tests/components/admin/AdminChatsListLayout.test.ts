import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { ref } from 'vue'
import AdminChats from '~/components/admin/AdminChats.vue'

// Every mount here shares one `useAsyncData('admin-chats')` entry, so a wrapper
// left mounted keeps its own fetcher closure — and its own `showArchived` —
// registered against that key. Without this, clicking the archive toggle in one
// test re-fetched through a previous test's component.
enableAutoUnmount(afterEach)

/**
 * SPEC-062 — the conversation list header carried two rows of controls for a
 * pane 340px wide. The top row was a hand-rolled segmented control filtering
 * All / Unread / Read, which duplicated a sort option and the unread chip, and
 * it pushed the refresh button away from the controls it belongs with.
 */

interface ChatSummary {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  last_message: string
  last_role: string
  unread: boolean
  archived?: boolean
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
    archived: false,
    ...overrides
  }
}

const callMock = vi.fn()
mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))

const toastAdd = vi.fn()
mockNuxtImport('useToast', () => () => ({ add: toastAdd }))

const typingState = { remoteTyping: ref(false), join: vi.fn(), ping: vi.fn(), leave: vi.fn() }
mockNuxtImport('useTypingChannel', () => () => typingState)

function listChats(chats: ChatSummary[]) {
  callMock.mockImplementation((path: string) => {
    if (path.startsWith('/chats?') || path === '/chats') return Promise.resolve(chats)
    if (path.startsWith('/chats/')) return Promise.resolve({ user_id: 'u1', messages: [] })
    return Promise.resolve(null)
  })
}

describe('components/admin/AdminChats.vue — list layout (SPEC-062)', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAdd.mockReset()
    clearNuxtData('admin-chats')
    listChats([])
  })

  it('no longer offers an All / Unread / Read segmented control', async () => {
    listChats([
      makeChat({ user_id: 'u1', display_name: 'Alice', unread: true }),
      makeChat({ user_id: 'u2', display_name: 'Bob', unread: false })
    ])

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const labels = wrapper.findAll('button').map(b => b.text().trim())
    expect(labels).not.toContain('All')
    expect(labels).not.toContain('Unread')
    expect(labels).not.toContain('Read')

    // Both rows are simply visible; unread is a chip and a sort, not a filter.
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('Bob')
  })

  it('sizes the search and sort controls to match, on one row with refresh', async () => {
    listChats([makeChat()])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const input = wrapper.findComponent({ name: 'UInput' })
    expect(input.props('size')).toBe('md')

    // The sort is a funnel, not a 160px select spelling out a choice that is
    // almost always the default.
    const sort = wrapper.findComponent('[data-testid="chats-sort"]')
    expect(sort.exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'USelect' }).exists()).toBe(false)

    const refresh = wrapper.find('[data-testid="chats-refresh"]')
    expect(refresh.exists()).toBe(true)

    // Same row, in reading order: search, then sort, then the buttons — with
    // refresh last, to the right of the sort control it belongs beside.
    const row = refresh.element.parentElement!
    const order = [...row.children].map(el =>
      el.getAttribute('data-testid') ?? el.querySelector('[data-testid]')?.getAttribute('data-testid')
    )
    expect(order).toEqual([
      'chats-search', 'chats-sort', 'chats-archived-toggle', 'chats-refresh'
    ])
  })

  it('lines the control strip up with the thread header across the splitter', async () => {
    listChats([makeChat({ user_id: 'u1', display_name: 'Alice' })])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    await wrapper.findAll('button').find(b => b.text().includes('Alice'))!.trigger('click')
    await flushPromises()

    // Both pinned rather than left to their content: the two rows sit either
    // side of the splitter handle, so a few pixels apart reads as misalignment.
    const strip = wrapper.find('[data-testid="chats-refresh"]').element.parentElement!
    const header = wrapper.find('header')
    const heightOf = (el: Element) => [...el.classList].find(c => /^h-\d/.test(c))

    expect(heightOf(strip)).toBeTruthy()
    expect(heightOf(strip)).toBe(heightOf(header.element))
  })

  it('refreshes the list from the button in that row', async () => {
    listChats([makeChat()])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()
    const before = callMock.mock.calls.filter(([p]) => String(p).startsWith('/chats')).length

    await wrapper.find('[data-testid="chats-refresh"]').trigger('click')
    await flushPromises()

    const after = callMock.mock.calls.filter(([p]) => String(p).startsWith('/chats')).length
    expect(after).toBeGreaterThan(before)
  })

  it('still searches by display name and last message', async () => {
    listChats([
      makeChat({ user_id: 'u1', display_name: 'Alice', last_message: 'about the tyres' }),
      makeChat({ user_id: 'u2', display_name: 'Bob', last_message: 'RM240 can?' })
    ])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    await wrapper.findComponent({ name: 'UInput' }).setValue('tyres')
    await flushPromises()

    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).not.toContain('Bob')
  })

  it('gives the conversation list pane a floor it cannot be dragged below', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const [list, thread] = wrapper.findComponent({ name: 'USplitter' }).props('items') as {
      minSize?: number
      defaultSize?: number
      maxSize?: number
    }[]

    expect(list!.minSize).toBeGreaterThanOrEqual(30)
    expect(list!.defaultSize).toBeGreaterThanOrEqual(30)
    // The two floors have to be able to coexist.
    expect(list!.minSize! + thread!.minSize!).toBeLessThanOrEqual(100)
  })

  it('names the empty state instead of only describing it', async () => {
    listChats([])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const empty = wrapper.findAllComponents({ name: 'UEmpty' })
      .find(e => e.props('description') === 'No conversations yet.')
    expect(empty, 'the empty list must render a UEmpty').toBeTruthy()
    expect(empty!.props('title')).toBeTruthy()
    expect(empty!.props('icon')).toBeTruthy()
  })

  it('distinguishes "nothing yet" from "nothing matches"', async () => {
    listChats([makeChat({ display_name: 'Alice', last_message: 'hi' })])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    await wrapper.findComponent({ name: 'UInput' }).setValue('nobody')
    await flushPromises()

    expect(wrapper.text()).toContain('No conversations match.')
    expect(wrapper.text()).not.toContain('No conversations yet.')
  })
})
