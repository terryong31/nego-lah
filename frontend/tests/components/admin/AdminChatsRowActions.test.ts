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
 * SPEC-063 — every row ended in a mail icon that did exactly one thing and read
 * as "send mail". An operator working a list needs more than one verb per row:
 * triage it, get it out of the way, or find out who they are talking to.
 *
 * Menu items are driven through the `items` prop rather than the rendered
 * popover: `UDropdownMenu` portals its content, so clicking a real item means
 * opening a floating element that isn't in this wrapper's tree.
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
  email?: string | null
  created_at?: string | null
  is_banned?: boolean
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
    email: 'alice@example.com',
    created_at: '2025-03-04T05:06:07Z',
    is_banned: false,
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
    if (path.includes('/archive')) return Promise.resolve({ archived: true, archived_at: 'now' })
    if (path.endsWith('/read')) return Promise.resolve({ unread: false, admin_last_read_at: 'now' })
    if (path.startsWith('/chats/')) return Promise.resolve({ user_id: 'u1', messages: [] })
    return Promise.resolve(null)
  })
}

type MenuItem = { label: string, icon?: string, onSelect?: () => void }

/**
 * The action menu for one row, flattened across its groups.
 *
 * Located by its trigger rather than by index: the control strip's sort funnel
 * is a `UDropdownMenu` too, and it comes first in the DOM.
 */
function menuFor(
  wrapper: ReturnType<typeof mountSuspended> extends Promise<infer W> ? W : never,
  userId = 'u1'
) {
  const testid = `chat-actions-${userId}`
  const menu = wrapper.findAllComponents({ name: 'UDropdownMenu' }).find((m) => {
    const el = m.element as HTMLElement
    return el.getAttribute?.('data-testid') === testid || !!el.querySelector?.(`[data-testid="${testid}"]`)
  })
  expect(menu, `no action menu for ${userId}`).toBeTruthy()
  return (menu!.props('items') as MenuItem[][]).flat()
}

function pick(items: MenuItem[], fragment: string) {
  const item = items.find(i => i.label?.toLowerCase().includes(fragment.toLowerCase()))
  expect(item, `no menu item matching "${fragment}" in ${items.map(i => i.label).join(', ')}`).toBeTruthy()
  return item!
}

function archiveCalls() {
  return callMock.mock.calls.filter(([path]) => String(path).includes('/archive'))
}

describe('components/admin/AdminChats.vue — row actions (SPEC-063)', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAdd.mockReset()
    clearNuxtData('admin-chats')
    listChats([makeChat()])
  })

  it('replaces the mail toggle with an actions menu', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.find('[data-testid="chat-read-toggle-u1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chat-actions-u1"]').exists()).toBe(true)

    const labels = menuFor(wrapper).map(i => i.label)
    expect(labels).toEqual(expect.arrayContaining([
      expect.stringMatching(/unread/i),
      expect.stringMatching(/archive/i),
      expect.stringMatching(/info/i)
    ]))
  })

  it('keeps the unread chip on the row — it is state, not an action', async () => {
    listChats([makeChat({ unread: true })])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(1)
  })

  it('marks a conversation read from the menu', async () => {
    listChats([makeChat({ unread: true })])
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    pick(menuFor(wrapper), 'read').onSelect!()
    await flushPromises()

    expect(callMock).toHaveBeenCalledWith('/chats/u1/read', { method: 'POST', body: { read: true } })
    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(0)
  })

  it('archives a conversation and drops it from the list at once', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()
    expect(wrapper.text()).toContain('Alice')

    pick(menuFor(wrapper), 'archive').onSelect!()
    await flushPromises()

    expect(archiveCalls()).toEqual([
      ['/chats/u1/archive', { method: 'POST', body: { archived: true } }]
    ])
    expect(wrapper.text()).not.toContain('Alice')
  })

  it('puts the row back when the archive write fails', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.reject(new Error('nope')))
    pick(menuFor(wrapper), 'archive').onSelect!()
    await flushPromises()

    expect(wrapper.text()).toContain('Alice')
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ color: 'error' }))
  })

  it('offers to restore a conversation while viewing the archive', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    listChats([makeChat({ archived: true })])
    await wrapper.find('[data-testid="chats-archived-toggle"]').trigger('click')
    await flushPromises()

    expect(callMock).toHaveBeenCalledWith('/chats?include_archived=true')
    expect(pick(menuFor(wrapper), 'restore')).toBeTruthy()
  })

  it('opens a user panel carrying the identity the row was given', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.findComponent({ name: 'USlideover' }).props('open')).toBe(false)

    pick(menuFor(wrapper), 'info').onSelect!()
    await flushPromises()

    const slideover = wrapper.findComponent({ name: 'USlideover' })
    expect(slideover.props('open')).toBe(true)
    // Titled for what it is, not by whoever it happens to be showing — the
    // display name is already the first line of the panel body.
    expect(slideover.props('title')).toBe('User Info')
    expect(slideover.props('description')).toBeUndefined()

    // The panel body is portalled to `document.body`, so it is not in this
    // wrapper's tree even though the component that owns it is.
    expect(document.body.textContent).toContain('alice@example.com')
    expect(document.body.textContent).toContain('u1')
  })

  it('leaves AI status to the thread header, which can actually change it', async () => {
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    pick(menuFor(wrapper), 'info').onSelect!()
    await flushPromises()

    const panel = document.querySelector('[role="dialog"]')
    expect(panel?.textContent).not.toContain('AI active')
    expect(panel?.textContent).not.toContain('AI paused')
  })
})
