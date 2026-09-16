import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import OrdersPage from '~/pages/orders.vue'

interface Order {
  item_name: string
  amount: number
  status: string
  created_at: string
  courier?: string | null
  tracking_number?: string | null
  tracking_url?: string | null
  shipped_at?: string | null
}

function makeOrder(overrides: Partial<Order> = {}): Order {
  return {
    item_name: 'Vintage Camera',
    amount: 123.4,
    status: 'completed',
    created_at: '2026-01-15T00:00:00Z',
    courier: null,
    tracking_number: null,
    tracking_url: null,
    shipped_at: null,
    ...overrides
  }
}

// Deferred promise helper so we can observe the `pending` state before
// resolving the session/orders fetch, matching the pattern used elsewhere
// (e.g. tests/pages/items/id.test.ts).
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

// Shape of the <script setup> bindings exposed on wrapper.vm in this test
// harness - used to reach internals (getStatusColor, formatDate) directly.
interface VmAny {
  getStatusColor: (status: string) => string
  formatDate: (dateStr: string) => string
}

const { userRef } = vi.hoisted(() => ({
  userRef: { __v_isRef: true, value: null as Record<string, unknown> | null }
}))

const { getSessionMock } = vi.hoisted(() => ({
  getSessionMock: vi.fn()
}))

const callMock = vi.fn()

mockNuxtImport('useApi', () => () => ({ call: callMock }))
mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useSupabaseClient', () => () => ({
  auth: { getSession: getSessionMock }
}))

describe('pages/orders.vue', () => {
  beforeEach(() => {
    userRef.value = null
    callMock.mockReset()
    getSessionMock.mockReset().mockResolvedValue({ data: { session: null } })
    // useAsyncData caches by key ('user-orders') on the shared nuxtApp
    // instance backing every mountSuspended() call in this file, so without
    // clearing it, only the first test would ever actually invoke the
    // fetcher.
    clearNuxtData('user-orders')
  })

  describe('uid resolution', () => {
    it('prefers the live session user id over useSupabaseUser when both are present', async () => {
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'session-uid' } } } })
      userRef.value = { id: 'reactive-uid' }
      callMock.mockResolvedValue({ orders: [] })

      await mountSuspended(OrdersPage)

      expect(callMock).toHaveBeenCalledWith('/payment/orders/user/session-uid')
    })

    it('falls back to useSupabaseUser().value.id when the session has no user', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value = { id: 'reactive-uid' }
      callMock.mockResolvedValue({ orders: [] })

      await mountSuspended(OrdersPage)

      expect(callMock).toHaveBeenCalledWith('/payment/orders/user/reactive-uid')
    })

    it('falls back to useSupabaseUser().value.id when the session promise resolves with no session at all', async () => {
      getSessionMock.mockResolvedValue({ data: {} })
      userRef.value = { id: 'reactive-uid-2' }
      callMock.mockResolvedValue({ orders: [] })

      await mountSuspended(OrdersPage)

      expect(callMock).toHaveBeenCalledWith('/payment/orders/user/reactive-uid-2')
    })

    it('returns [] and never calls the API when neither the session nor the reactive user have an id', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value = null

      const wrapper = await mountSuspended(OrdersPage)

      expect(callMock).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('No Orders Yet')
    })
  })

  describe('loading state', () => {
    it('shows the loading skeletons while the session/orders fetch is in flight', async () => {
      userRef.value = { id: 'u1' }
      const { promise } = deferred<{ data: { session: null } }>()
      getSessionMock.mockReturnValue(promise)

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.findComponent({ name: 'USkeleton' }).exists()).toBe(true)
      expect(wrapper.text()).not.toContain('No Orders Yet')
      expect(wrapper.text()).not.toContain('Vintage Camera')
    })
  })

  describe('empty state', () => {
    it('shows "No Orders Yet" with a link back to the storefront when there are no orders', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({ orders: [] })

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('No Orders Yet')
      expect(wrapper.text()).toContain('Bargain with our AI model and secure a deal to start purchasing!')
      const button = wrapper.findComponent({ name: 'UButton' })
      expect(button.props('to')).toBe('/')
      expect(button.props('label')).toBe('Explore Storefront')
    })

    it('treats a response with no `orders` property as empty (via the ?? [] fallback)', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({})

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('No Orders Yet')
    })

    it('falls back to the empty default state when the orders fetch rejects', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockRejectedValue(new Error('network down'))

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('No Orders Yet')
    })
  })

  describe('successful render', () => {
    it('renders a row per order: item name, formatted price, capitalized status badge, and formatted date', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({
        orders: [makeOrder({ item_name: 'Vintage Camera', amount: 123.4, status: 'completed', created_at: '2026-01-15T00:00:00Z' })]
      })

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('Vintage Camera')
      expect(wrapper.text()).toContain('RM 123.40')
      expect(wrapper.text()).not.toContain('No Orders Yet')

      const badge = wrapper.findComponent({ name: 'UBadge' })
      expect(badge.exists()).toBe(true)
      expect(badge.props('color')).toBe('success')
      expect(badge.text()).toBe('completed')

      expect(wrapper.text()).toContain(
        new Date('2026-01-15T00:00:00Z').toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' })
      )
    })

    it('replaces underscores with spaces in the status badge label', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({
        orders: [makeOrder({ status: 'pending_review' })]
      })

      const wrapper = await mountSuspended(OrdersPage)

      const badge = wrapper.findComponent({ name: 'UBadge' })
      expect(badge.text()).toBe('pending review')
    })

    it('calls the user-orders endpoint exactly once for the resolved uid', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'abc-123' } } } })
      callMock.mockResolvedValue({ orders: [makeOrder()] })

      await mountSuspended(OrdersPage)

      expect(callMock).toHaveBeenCalledTimes(1)
      expect(callMock).toHaveBeenCalledWith('/payment/orders/user/abc-123')
    })
  })

  describe('shipment tracking (SPEC-069)', () => {
    it('renders the courier and tracking number as an external link', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({
        orders: [makeOrder({
          status: 'shipped',
          courier: 'J&T Express',
          tracking_number: '630123456789',
          tracking_url: 'https://www.jtexpress.my/tracking?billcode=630123456789'
        })]
      })

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('J&T Express')
      expect(wrapper.text()).toContain('630123456789')

      const link = wrapper.find('a[href="https://www.jtexpress.my/tracking?billcode=630123456789"]')
      expect(link.exists()).toBe(true)
      expect(link.attributes('target')).toBe('_blank')
      // Opening a carrier's site must not hand it a window.opener handle.
      expect(link.attributes('rel')).toContain('noopener')
    })

    it('shows the courier as plain text when the carrier has no tracking URL', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({
        orders: [makeOrder({
          status: 'shipped',
          courier: 'Uncle Lim Lorry',
          tracking_number: 'AB123',
          tracking_url: null
        })]
      })

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('Uncle Lim Lorry')
      expect(wrapper.text()).toContain('AB123')
      expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)
    })

    it('renders an em dash for an order that has not shipped', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({ orders: [makeOrder({ status: 'paid' })] })

      const wrapper = await mountSuspended(OrdersPage)

      expect(wrapper.text()).toContain('\u2014')
    })
  })

  describe('getStatusColor', () => {
    it.each([
      ['completed', 'success'],
      ['delivered', 'success'],
      ['paid', 'info'],
      ['shipped', 'info'],
      ['pending', 'warning'],
      ['refunded', 'neutral'],
      ['cancelled', 'error'],
      ['some_unknown_status', 'error']
    ])('maps status "%s" to color "%s"', async (status, expected) => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({ orders: [] })

      const wrapper = await mountSuspended(OrdersPage)

      expect((wrapper.vm as unknown as VmAny).getStatusColor(status)).toBe(expected)
    })

    it('matches case-insensitively (uppercase status still resolves to its color)', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({ orders: [] })

      const wrapper = await mountSuspended(OrdersPage)

      expect((wrapper.vm as unknown as VmAny).getStatusColor('COMPLETED')).toBe('success')
      expect((wrapper.vm as unknown as VmAny).getStatusColor('Refunded')).toBe('neutral')
    })
  })

  describe('formatDate', () => {
    it('returns "-" for a falsy/empty date string', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({ orders: [] })

      const wrapper = await mountSuspended(OrdersPage)

      expect((wrapper.vm as unknown as VmAny).formatDate('')).toBe('-')
    })

    it('formats an ISO date string using en-MY locale formatting', async () => {
      userRef.value = { id: 'u1' }
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'u1' } } } })
      callMock.mockResolvedValue({ orders: [] })

      const wrapper = await mountSuspended(OrdersPage)

      expect((wrapper.vm as unknown as VmAny).formatDate('2026-01-15T00:00:00Z')).toBe(
        new Date('2026-01-15T00:00:00Z').toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' })
      )
    })
  })
})
