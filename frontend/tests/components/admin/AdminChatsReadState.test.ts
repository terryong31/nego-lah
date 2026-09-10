import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { ref } from 'vue'
import AdminChats from '~/components/admin/AdminChats.vue'

/**
 * SPEC-053 — "mark as read" in the console.
 *
 * The dot used to be derived from `last_role === 'human'`, so nothing the
 * operator did could clear it. These cover the two ways it now clears — opening
 * a thread, and the explicit per-row toggle — plus the requirement that the
 * toggle does NOT also select the row (an operator triaging a list should be
 * able to dismiss a thread without loading it).
 */

interface ChatSummary {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  last_message: string
  last_role: string
  unread: boolean
  admin_last_read_at?: string | null
}

function makeChat(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return {
    user_id: 'u1',
    display_name: 'Alice',
    avatar_url: null,
    message_count: 3,
    last_message: 'Hi there',
    last_role: 'human',
    unread: true,
    admin_last_read_at: null,
    ...overrides
  }
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

function readCalls() {
  return callMock.mock.calls.filter(([path]) => String(path).endsWith('/read'))
}

describe('components/admin/AdminChats.vue — read state (SPEC-053)', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAdd.mockReset()
    typingState.join.mockReset()
    clearNuxtData('admin-chats')

    callMock.mockImplementation((path: string, opts?: { body?: { read?: boolean } }) => {
      if (path === '/chats') return Promise.resolve([])
      // Mirrors the real endpoint: it echoes the resulting state back, so
      // `read: false` answers `unread: true` with a cleared watermark.
      if (path.endsWith('/read')) {
        const read = opts?.body?.read !== false
        return Promise.resolve({
          user_id: 'u1',
          unread: !read,
          admin_last_read_at: read ? '2026-09-09T13:00:00Z' : null
        })
      }
      if (path.startsWith('/chats/') && path.includes('/message')) return Promise.resolve({ ok: true })
      if (path.startsWith('/chats/')) return Promise.resolve({ user_id: 'u1', messages: [] })
      return Promise.resolve(null)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('marks a conversation read when it is opened, and clears the dot immediately', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ unread: true })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(1)

    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(readCalls()).toEqual([
      ['/chats/u1/read', { method: 'POST', body: { read: true } }]
    ])
    // Optimistic: the dot is gone without waiting for a list refresh.
    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(0)
  })

  it('does not re-mark a conversation that is already read', async () => {
    callMock.mockImplementationOnce(() =>
      Promise.resolve([makeChat({ unread: false, admin_last_read_at: '2026-09-09T13:00:00Z' })])
    )

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    const chatButton = wrapper.findAll('button').find(b => b.text().includes('Alice'))
    await chatButton!.trigger('click')
    await flushPromises()

    expect(readCalls()).toEqual([])
  })

  /** The row's read action, reached through the menu that replaced the mail
   *  icon (SPEC-063). `UDropdownMenu` portals its content, so the item is
   *  driven through the `items` prop rather than a rendered click target, and
   *  the menu is found by its trigger — the control strip's sort funnel is a
   *  `UDropdownMenu` as well, and it comes first in the DOM. */
  function readAction(wrapper: {
    findAllComponents: (m: { name: string }) => { element: HTMLElement, props: (p: string) => unknown }[]
  }) {
    const menu = wrapper.findAllComponents({ name: 'UDropdownMenu' }).find(m =>
      m.element.getAttribute?.('data-testid') === 'chat-actions-u1'
      || !!m.element.querySelector?.('[data-testid="chat-actions-u1"]')
    )
    expect(menu, 'no action menu on the row').toBeTruthy()
    const groups = menu!.props('items') as { label: string, onSelect?: () => void }[][]
    const item = groups.flat().find(i => /read/i.test(i.label))
    expect(item, 'no read action in the row menu').toBeTruthy()
    return item!
  }

  it('toggles read state from the row menu without opening the conversation', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ unread: true })]))

    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    expect(wrapper.find('[data-testid="chat-actions-u1"]').exists()).toBe(true)

    readAction(wrapper).onSelect!()
    await flushPromises()

    expect(readCalls()).toEqual([
      ['/chats/u1/read', { method: 'POST', body: { read: true } }]
    ])
    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(0)
    // The thread was NOT loaded — triage without reading is the point.
    expect(callMock).not.toHaveBeenCalledWith('/chats/u1?limit=100')
    expect(typingState.join).not.toHaveBeenCalled()
  })

  it('marks a read conversation back to unread from the same control', async () => {
    callMock.mockImplementationOnce(() =>
      Promise.resolve([makeChat({ unread: false, admin_last_read_at: '2026-09-09T13:00:00Z' })])
    )
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    readAction(wrapper).onSelect!()
    await flushPromises()

    expect(readCalls()).toEqual([
      ['/chats/u1/read', { method: 'POST', body: { read: false } }]
    ])
    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(1)
  })

  it('restores the dot and warns when the server rejects the change', async () => {
    callMock.mockImplementationOnce(() => Promise.resolve([makeChat({ unread: true })]))
    const wrapper = await mountSuspended(AdminChats)
    await flushPromises()

    callMock.mockImplementationOnce(() => Promise.reject(new Error('nope')))

    readAction(wrapper).onSelect!()
    await flushPromises()

    expect(wrapper.findAllComponents({ name: 'UChip' }).length).toBe(1)
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ color: 'error' }))
  })
})
