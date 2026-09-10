import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import AdminOrders from '~/components/admin/AdminOrders.vue'

const { callMock, toastAddMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

interface Order {
  id: string
  item_name: string
  amount: number
  status: string
  buyer_name?: string
  buyer_email?: string
  recipient_name?: string
  address?: string
  phone?: string
  notes?: string
  created_at: string
  courier?: string | null
  tracking_number?: string | null
  tracking_url?: string | null
  shipped_at?: string | null
  delivered_at?: string | null
}

function makeOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: 'o1',
    item_name: 'Widget',
    amount: 12.5,
    status: 'pending_info',
    buyer_name: 'Alice',
    buyer_email: 'alice@example.com',
    recipient_name: 'Alice A',
    address: '123 Street',
    phone: '0123456789',
    notes: '',
    created_at: '2026-01-15T00:00:00Z',
    ...overrides
  }
}

function makeResponse(orders: Order[] = [makeOrder()]) {
  return {
    orders,
    stats: {
      total_orders: orders.length,
      total_sales: orders.reduce((sum, o) => sum + o.amount, 0)
    }
  }
}

// Shape of the <script setup> bindings exposed on wrapper.vm in this test harness -
// used purely to reach internals (statusColor, changeStatus, ...) without `any`.
interface VmAny {
  orders: Order[]
  busy: string | null
  expanded: Record<number, boolean>
  statusColor: (s: string) => string
  changeStatus: (o: Order, status: string) => Promise<void>
  remove: (o: Order) => Promise<void>
  formatDate: (d: string) => string
  hasShippingInfo: (o: Order) => string | undefined
  shipmentDraft: (o: Order) => { courier: string, trackingNumber: string, trackingUrl: string, notify: boolean }
  recordShipment: (o: Order) => Promise<void>
}

describe('components/admin/AdminOrders.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    // `useAsyncData('admin-orders', ...)` caches its result on the shared Nuxt
    // app instance that backs every mountSuspended() call in this file - since
    // mountSuspended() never truly unmounts the previous wrapper's component
    // tree, a plain remount reuses the cached ("success") data and skips
    // refetching. Reset the cache before each test so every mount performs a
    // fresh call to `/orders` against that test's own mocked response.
    clearNuxtData('admin-orders')
  })

  it('fetches /orders on mount and renders order count', async () => {
    callMock.mockResolvedValueOnce(makeResponse())
    const wrapper = await mountSuspended(AdminOrders)

    expect(callMock).toHaveBeenCalledWith('/orders')
    expect(wrapper.text()).toContain('1 order(s)')
  })

  it('falls back to the empty default state when the initial fetch rejects', async () => {
    callMock.mockRejectedValueOnce(new Error('network down'))
    const wrapper = await mountSuspended(AdminOrders)

    expect(wrapper.text()).toContain('0 order(s)')
    expect((wrapper.vm as VmAny).orders).toEqual([])
  })

  describe('statusColor', () => {
    it.each([
      ['delivered', 'success'],
      ['shipped', 'info'],
      ['confirmed', 'info'],
      ['pending_info', 'warning'],
      ['refunded', 'neutral'],
      ['cancelled', 'error'],
      ['some_unknown_status', 'error']
    ])('maps status "%s" to color "%s"', async (status, expected) => {
      callMock.mockResolvedValueOnce(makeResponse())
      const wrapper = await mountSuspended(AdminOrders)
      expect((wrapper.vm as VmAny).statusColor(status)).toBe(expected)
    })
  })

  describe('changeStatus', () => {
    it('is a no-op when the new status equals the current status', async () => {
      const order = makeOrder({ status: 'confirmed' })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)

      await (wrapper.vm as VmAny).changeStatus(order, 'confirmed')

      // Only the initial GET /orders call happened - no PUT was issued.
      expect(callMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('PUTs the new status, mutates the order in place, and shows a success toast', async () => {
      const order = makeOrder({ status: 'pending_info' })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      callMock.mockResolvedValueOnce({})

      await (wrapper.vm as VmAny).changeStatus(order, 'confirmed')

      expect(callMock).toHaveBeenCalledWith('/orders/o1/status', {
        method: 'PUT',
        body: { status: 'confirmed' }
      })
      expect(order.status).toBe('confirmed')
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Order marked confirmed', color: 'success' })
      expect((wrapper.vm as VmAny).busy).toBeNull()
    })

    it('shows an error toast using the API detail message when the PUT fails', async () => {
      const order = makeOrder({ status: 'pending_info' })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      callMock.mockRejectedValueOnce({ data: { detail: 'Invalid transition' } })

      await (wrapper.vm as VmAny).changeStatus(order, 'shipped')

      expect(order.status).toBe('pending_info')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Update failed',
        description: 'Invalid transition',
        color: 'error'
      })
      expect((wrapper.vm as VmAny).busy).toBeNull()
    })

    it('falls back to err.message when the API error has no detail', async () => {
      const order = makeOrder({ status: 'pending_info' })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      callMock.mockRejectedValueOnce(new Error('boom'))

      await (wrapper.vm as VmAny).changeStatus(order, 'shipped')

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Update failed',
        description: 'boom',
        color: 'error'
      })
    })
  })

  describe('remove', () => {
    it('does nothing when window.confirm returns false', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
      const order = makeOrder()
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)

      await (wrapper.vm as VmAny).remove(order)

      expect(window.confirm).toHaveBeenCalledWith('Delete this order for "Widget"?')
      // Only the initial GET /orders call happened - no DELETE was issued.
      expect(callMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('deletes, shows a success toast, and refreshes the list when confirmed', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const order = makeOrder()
      callMock.mockResolvedValueOnce(makeResponse([order])) // initial load
      const wrapper = await mountSuspended(AdminOrders)
      callMock.mockResolvedValueOnce({}) // DELETE
      callMock.mockResolvedValueOnce(makeResponse([])) // refresh() after delete

      await (wrapper.vm as VmAny).remove(order)

      expect(callMock).toHaveBeenCalledWith('/orders/o1', { method: 'DELETE' })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Order deleted', color: 'success' })
      expect(callMock).toHaveBeenCalledTimes(3)
      expect((wrapper.vm as VmAny).busy).toBeNull()
    })

    it('falls back to "Untitled" in the confirm message when item_name is missing', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
      const order = makeOrder({ item_name: '' })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)

      await (wrapper.vm as VmAny).remove(order)

      expect(confirmSpy).toHaveBeenCalledWith('Delete this order for "Untitled"?')
    })

    it('shows an error toast using the API detail message when the DELETE fails', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const order = makeOrder()
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      callMock.mockRejectedValueOnce({ data: { detail: 'Order is locked' } })

      await (wrapper.vm as VmAny).remove(order)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Delete failed',
        description: 'Order is locked',
        color: 'error'
      })
      expect((wrapper.vm as VmAny).busy).toBeNull()
    })

    it('falls back to err.message when the DELETE error has no detail', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const order = makeOrder()
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      callMock.mockRejectedValueOnce(new Error('server exploded'))

      await (wrapper.vm as VmAny).remove(order)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Delete failed',
        description: 'server exploded',
        color: 'error'
      })
    })
  })

  describe('formatDate', () => {
    it('formats an ISO date string using en-MY locale formatting', async () => {
      callMock.mockResolvedValueOnce(makeResponse())
      const wrapper = await mountSuspended(AdminOrders)
      expect((wrapper.vm as VmAny).formatDate('2026-01-15T00:00:00Z')).toBe(
        new Date('2026-01-15T00:00:00Z').toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' })
      )
    })

    it('returns "-" for a falsy date', async () => {
      callMock.mockResolvedValueOnce(makeResponse())
      const wrapper = await mountSuspended(AdminOrders)
      expect((wrapper.vm as VmAny).formatDate('')).toBe('-')
    })
  })

  describe('hasShippingInfo / expandable row', () => {
    it('returns a truthy value when at least one shipping field is present', async () => {
      callMock.mockResolvedValueOnce(makeResponse())
      const wrapper = await mountSuspended(AdminOrders)
      const vm = wrapper.vm as VmAny
      expect(vm.hasShippingInfo(makeOrder({ recipient_name: 'Bob', address: undefined, phone: undefined }))).toBeTruthy()
      expect(vm.hasShippingInfo(makeOrder({ recipient_name: undefined, address: 'Somewhere', phone: undefined }))).toBeTruthy()
      expect(vm.hasShippingInfo(makeOrder({ recipient_name: undefined, address: undefined, phone: '012' }))).toBeTruthy()
    })

    it('returns a falsy value when no shipping fields are present', async () => {
      callMock.mockResolvedValueOnce(makeResponse())
      const wrapper = await mountSuspended(AdminOrders)
      const vm = wrapper.vm as VmAny
      expect(vm.hasShippingInfo(makeOrder({ recipient_name: undefined, address: undefined, phone: undefined }))).toBeFalsy()
    })

    it('renders shipping details in the expanded slot content when the row is expanded', async () => {
      const order = makeOrder({
        recipient_name: 'Bob Recipient',
        address: '456 Lane\nCity',
        phone: '019-999-9999',
        notes: 'Leave at door'
      })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)

      ;(wrapper.vm as VmAny).expanded = { 0: true }
      await wrapper.vm.$nextTick()

      const text = wrapper.text()
      expect(text).toContain('Shipping Details')
      expect(text).toContain('Bob Recipient')
      expect(text).toContain('456 Lane')
      expect(text).toContain('019-999-9999')
      expect(text).toContain('Leave at door')
    })

    it('shows the "no shipping info" message when the row is expanded but has no shipping data', async () => {
      const order = makeOrder({ recipient_name: undefined, address: undefined, phone: undefined, notes: undefined })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)

      ;(wrapper.vm as VmAny).expanded = { 0: true }
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('No shipping info collected yet.')
    })
  })

  describe('rendered expand-toggle button (via @vue/test-utils, not calling toggleExpanded() directly)', () => {
    it('clicking the expand button reveals the shipping-details panel, clicking again collapses it', async () => {
      const order = makeOrder({
        recipient_name: 'Bob Recipient',
        address: '456 Lane',
        phone: '019-999-9999'
      })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)

      expect(wrapper.text()).not.toContain('Shipping Details')

      const expandButton = wrapper.find('button[aria-label="Expand"]')
      expect(expandButton.exists()).toBe(true)

      await expandButton.trigger('click')
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('Shipping Details')
      expect(wrapper.text()).toContain('Bob Recipient')

      await expandButton.trigger('click')
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).not.toContain('Shipping Details')
    })
  })

  describe('rendered Refresh button', () => {
    it('re-invokes the /orders fetch and re-renders with the refreshed data when clicked', async () => {
      callMock.mockResolvedValueOnce(makeResponse([makeOrder({ id: 'o1' })]))
      const wrapper = await mountSuspended(AdminOrders)

      expect(wrapper.text()).toContain('1 order(s)')
      expect(callMock).toHaveBeenCalledTimes(1)

      callMock.mockResolvedValueOnce(makeResponse([
        makeOrder({ id: 'o1' }),
        makeOrder({ id: 'o2', item_name: 'Gadget', amount: 30 })
      ]))

      const refreshButton = wrapper.findAll('button').find(b => b.text().includes('Refresh'))
      expect(refreshButton).toBeTruthy()

      await refreshButton!.trigger('click')
      await flushPromises()
      await wrapper.vm.$nextTick()

      expect(callMock).toHaveBeenCalledTimes(2)
      expect(callMock).toHaveBeenNthCalledWith(2, '/orders')
      expect(wrapper.text()).toContain('2 order(s)')
    })
  })

  describe('rendered per-row controls (SPEC-064 overflow menu)', () => {
    /** The row's action menu, flattened across its groups. */
    function rowMenu(wrapper: { findComponent: (o: object) => { props: (p: string) => unknown } }) {
      const groups = wrapper.findComponent({ name: 'UDropdownMenu' }).props('items') as
        { label: string, onSelect?: () => void }[][]
      return groups.flat()
    }

    it('changes status from the overflow menu, the select having been redundant with the Status column', async () => {
      const order = makeOrder({ status: 'pending_info' })
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      await flushPromises()
      callMock.mockResolvedValueOnce({})

      expect(wrapper.findComponent({ name: 'USelect' }).exists()).toBe(false)

      const confirm = rowMenu(wrapper).find(i => /confirmed/i.test(i.label))
      expect(confirm, 'the transition must survive losing the select').toBeTruthy()
      confirm!.onSelect!()
      await flushPromises()

      expect(callMock).toHaveBeenCalledWith('/orders/o1/status', {
        method: 'PUT',
        body: { status: 'confirmed' }
      })
      expect(order.status).toBe('confirmed')
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Order marked confirmed', color: 'success' })
    })

    it('deletes from the overflow menu, confirming via window.confirm first', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const order = makeOrder()
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      await flushPromises()
      callMock.mockResolvedValueOnce({}) // DELETE
      callMock.mockResolvedValueOnce(makeResponse([])) // refresh() after delete

      rowMenu(wrapper).find(i => /delete/i.test(i.label))!.onSelect!()
      await flushPromises()

      expect(window.confirm).toHaveBeenCalledWith('Delete this order for "Widget"?')
      expect(callMock).toHaveBeenCalledWith('/orders/o1', { method: 'DELETE' })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Order deleted', color: 'success' })
    })

    it('does not call the API when window.confirm is declined', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
      const order = makeOrder()
      callMock.mockResolvedValueOnce(makeResponse([order]))
      const wrapper = await mountSuspended(AdminOrders)
      await flushPromises()
      callMock.mockClear()

      rowMenu(wrapper).find(i => /delete/i.test(i.label))!.onSelect!()
      await flushPromises()

      expect(callMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })
  })
})

// ---------------------------------------------------------------------------
// Postage (SPEC-057)
//
// One submit records the tracking AND tells the buyer. The tests below are
// mostly about the seller's feedback loop: a shipment that saved but whose
// notification failed must NOT read as a clean success, or nobody chases it and
// the buyer is left staring at "confirmed" while the parcel is in transit.
// ---------------------------------------------------------------------------

describe('recording postage', () => {
  const shipped = (over: Partial<Order> = {}) => ({
    id: 'o1',
    courier: 'J&T Express',
    tracking_number: '630123456789',
    tracking_url: 'https://www.jtexpress.my/tracking?billcode=630123456789',
    shipped_at: '2026-09-10T00:00:00Z',
    ...over
  })

  // Routed by path rather than by a mockResolvedValueOnce queue: the initial
  // `useAsyncData('admin-orders')` fetch is not guaranteed to consume exactly
  // one queued value, and a single skipped fetch shifts every later response
  // onto the wrong call.
  let shipmentReply: unknown

  function routeCalls(orders: Order[]) {
    callMock.mockImplementation((path: string) => {
      if (path === '/orders') return Promise.resolve(makeResponse(orders))
      if (path.endsWith('/shipment')) {
        return shipmentReply instanceof Error
          ? Promise.reject(shipmentReply)
          : Promise.resolve(shipmentReply)
      }
      return Promise.resolve({})
    })
  }

  async function mountWith(...orders: Order[]) {
    routeCalls(orders.length ? orders : [makeOrder()])
    const wrapper = await mountSuspended(AdminOrders)
    await flushPromises()
    return wrapper
  }

  // This block is a sibling of the main describe, so it never inherited that
  // one's reset. `useAsyncData('admin-orders')` is shared across every mount in
  // the file, and `recordShipment` mutates the order object in place — so
  // without this, one test's shipped order became the next test's starting
  // state, and drafts seeded from `shipped_at` (SPEC-064) read the wrong one.
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    shipmentReply = undefined
    clearNuxtData('admin-orders')
  })

  it('PUTs courier, tracking number and the notify flag', async () => {
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const order = vm.orders[0]!

    const draft = vm.shipmentDraft(order)
    draft.courier = 'J&T Express'
    draft.trackingNumber = '630123456789'

    shipmentReply = { order: shipped(), notified: { email: true, chat: true } }
    await vm.recordShipment(order)

    expect(callMock).toHaveBeenLastCalledWith('/orders/o1/shipment', {
      method: 'PUT',
      body: {
        courier: 'J&T Express',
        tracking_number: '630123456789',
        tracking_url: undefined,
        notify: true
      }
    })
  })

  it('will not submit without both a courier and a tracking number', async () => {
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const order = vm.orders[0]!
    callMock.mockClear()
    callMock.mockResolvedValue({})

    vm.shipmentDraft(order).courier = 'J&T Express'
    vm.shipmentDraft(order).trackingNumber = '   '
    await vm.recordShipment(order)

    expect(callMock).not.toHaveBeenCalled()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ color: 'warning' })
    )
  })

  it('reflects the shipment on the row without a refetch', async () => {
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const order = vm.orders[0]!
    vm.shipmentDraft(order).courier = 'J&T Express'
    vm.shipmentDraft(order).trackingNumber = '630123456789'

    shipmentReply = { order: shipped(), notified: { email: true, chat: true } }
    await vm.recordShipment(order)

    expect(order.status).toBe('shipped')
    expect(order.tracking_number).toBe('630123456789')
    expect(order.tracking_url).toContain('jtexpress')
  })

  it('warns rather than congratulates when the buyer could not be notified', async () => {
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const order = vm.orders[0]!
    vm.shipmentDraft(order).courier = 'J&T Express'
    vm.shipmentDraft(order).trackingNumber = '630123456789'

    shipmentReply = { order: shipped(), notified: { email: false, chat: false } }
    await vm.recordShipment(order)

    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        color: 'warning',
        description: 'Shipment saved, but the buyer could not be notified.'
      })
    )
  })

  it('does not warn about a notification the seller opted out of', async () => {
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const order = vm.orders[0]!
    vm.shipmentDraft(order).courier = 'J&T Express'
    vm.shipmentDraft(order).trackingNumber = '630123456789'
    vm.shipmentDraft(order).notify = false

    shipmentReply = { order: shipped(), notified: { email: false, chat: false } }
    await vm.recordShipment(order)

    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        color: 'success',
        description: 'Saved without notifying the buyer.'
      })
    )
  })

  it('surfaces the backend reason when the write itself fails', async () => {
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const order = vm.orders[0]!
    vm.shipmentDraft(order).courier = 'J&T Express'
    vm.shipmentDraft(order).trackingNumber = '630123456789'

    // Snapshot rather than assert literals: `mountSuspended` reuses this
    // file's component tree, so the row may carry values an earlier test set.
    // The property under test is that a FAILED write changes nothing.
    const before = JSON.stringify(order)
    shipmentReply = Object.assign(new Error('failed'), { data: { detail: 'Order not found' } })
    await vm.recordShipment(order)

    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: 'error', description: 'Order not found' })
    )
    expect(JSON.stringify(order)).toBe(before)
  })

  it('seeds the draft from an already-shipped order', async () => {
    const wrapper = await mountWith(makeOrder(shipped({ status: 'shipped' }) as Partial<Order>))
    const vm = wrapper.vm as VmAny

    const draft = vm.shipmentDraft(vm.orders[0]!)
    expect(draft.courier).toBe('J&T Express')
    expect(draft.trackingNumber).toBe('630123456789')
  })

  it('keeps a separate draft per order', async () => {
    // Drafts are keyed by order id so that expanding two rows and typing in
    // both cannot let one overwrite the other on submit. Exercised against the
    // orders directly: `mountSuspended` reuses this file's component tree, so
    // `vm.orders` is not a reliable way to get two fresh rows.
    const wrapper = await mountWith()
    const vm = wrapper.vm as VmAny
    const first = makeOrder({ id: 'draft-a' })
    const second = makeOrder({ id: 'draft-b', item_name: 'Other' })

    vm.shipmentDraft(first).trackingNumber = 'AAA'
    vm.shipmentDraft(second).trackingNumber = 'BBB'

    expect(vm.shipmentDraft(first).trackingNumber).toBe('AAA')
    expect(vm.shipmentDraft(second).trackingNumber).toBe('BBB')
  })
})
