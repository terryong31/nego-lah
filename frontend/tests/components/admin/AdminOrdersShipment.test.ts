import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { defineComponent } from 'vue'
import { UApp } from '#components'
import AdminOrders from '~/components/admin/AdminOrders.vue'

/**
 * SPEC-064 — an order row stated its status three times, and the one thing the
 * seller actually does with an order (post it) was a form buried inside an
 * expanded row.
 */

const { callMock, toastAddMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn()
}))
mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

enableAutoUnmount(afterEach)

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
  created_at: string
  courier?: string | null
  tracking_number?: string | null
  tracking_url?: string | null
  shipped_at?: string | null
  delivered_at?: string | null
}

function makeOrder(over: Partial<Order> = {}): Order {
  return {
    id: 'o1',
    item_name: 'Widget',
    amount: 12.5,
    status: 'confirmed',
    buyer_name: 'Alice',
    buyer_email: 'alice@example.com',
    recipient_name: 'Alice A',
    address: '123 Street',
    phone: '0123456789',
    created_at: '2026-01-15T00:00:00Z',
    ...over
  }
}

function routeCalls(orders: Order[], shipmentReply?: unknown) {
  callMock.mockImplementation((path: string) => {
    if (path === '/orders') {
      return Promise.resolve({
        orders,
        stats: { total_orders: orders.length, total_sales: 0 }
      })
    }
    if (path.endsWith('/shipment')) return Promise.resolve(shipmentReply ?? {})
    return Promise.resolve({})
  })
}

// `UTooltip` reads a provider context that `UApp` installs, and `app.vue` wraps
// the whole application in one — so mounting the component bare is the thing
// that is unrealistic here, not the tooltip.
const Host = defineComponent({
  components: { UApp, AdminOrders },
  template: '<UApp><AdminOrders /></UApp>'
})

async function mountWith(orders: Order[], shipmentReply?: unknown) {
  routeCalls(orders, shipmentReply)
  const host = await mountSuspended(Host)
  await flushPromises()
  return host.findComponent(AdminOrders)
}

type Vm = {
  orders: Order[]
  shipmentDraft: (o: Order) => { courier: string, trackingNumber: string, trackingUrl: string, notify: boolean }
  openShipment: (o: Order) => void
  recordShipment: (o: Order) => Promise<void>
  shippingOrder: Order | null
}

function button(wrapper: { findAll: (s: string) => { text: () => string, trigger: (e: string) => Promise<void> }[] }, label: string) {
  return wrapper.findAll('button').find(b => b.text().trim() === label)
}

describe('components/admin/AdminOrders.vue — lifecycle actions (SPEC-064)', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    clearNuxtData('admin-orders')
  })

  it('drops the status select — the Status column already says it', async () => {
    const wrapper = await mountWith([makeOrder({ status: 'confirmed' })])

    expect(wrapper.findComponent({ name: 'USelect' }).exists()).toBe(false)
  })

  it('offers Ship on a confirmed order', async () => {
    const wrapper = await mountWith([makeOrder({ status: 'confirmed' })])

    const ship = button(wrapper, 'Ship')
    expect(ship, 'a confirmed order is one the seller still has to post').toBeTruthy()
  })

  it('offers Edit shipment once it has been posted, prefilled with what was recorded', async () => {
    const order = makeOrder({
      status: 'shipped',
      courier: 'J&T Express',
      tracking_number: '630123456789',
      tracking_url: 'https://jt.example/630123456789',
      shipped_at: '2026-09-01T00:00:00Z'
    })
    const wrapper = await mountWith([order])

    const edit = button(wrapper, 'Edit shipment')
    expect(edit, 'a typo must be fixable without expanding anything').toBeTruthy()

    await edit!.trigger('click')
    await flushPromises()

    const vm = wrapper.vm as unknown as Vm
    const draft = vm.shipmentDraft(vm.orders[0]!)
    expect(draft.courier).toBe('J&T Express')
    expect(draft.trackingNumber).toBe('630123456789')
    expect(draft.trackingUrl).toBe('https://jt.example/630123456789')
  })

  it('opens the postage form in a modal, not behind a chevron', async () => {
    const wrapper = await mountWith([makeOrder({ status: 'confirmed' })])

    expect(wrapper.findComponent({ name: 'UModal' }).props('open')).toBe(false)

    await button(wrapper, 'Ship')!.trigger('click')
    await flushPromises()

    expect(wrapper.findComponent({ name: 'UModal' }).props('open')).toBe(true)
    expect(document.body.textContent).toContain('Courier')
  })

  it('tucks the tracking-link footnote into a tooltip at the end of its label row', async () => {
    // Mounted from the host here: the modal body is portalled out of the
    // component's own subtree, so the tooltip is reachable from the app root
    // rather than from `AdminOrders`.
    routeCalls([makeOrder({ status: 'confirmed' })])
    const host = await mountSuspended(Host)
    await flushPromises()
    const wrapper = host.findComponent(AdminOrders)

    await button(wrapper, 'Ship')!.trigger('click')
    await flushPromises()

    // `findAllComponents`, not `findComponent`: VTU hands back an error wrapper
    // for a teleported match, which `.exists()` then reports as absent.
    const [tooltip] = host.findAllComponents({ name: 'UTooltip' })
    expect(tooltip, 'the hint must be a tooltip, not body text').toBeTruthy()
    expect(tooltip!.props('text')).toBe('Leave blank to use the courier\'s standard tracking page.')
    expect(tooltip!.props('delayDuration')).toBe(150)

    // A real button, so the hint is reachable without a pointer.
    const trigger = document.querySelector('[data-testid="tracking-url-hint"]')
    expect(trigger).toBeTruthy()
    expect(trigger!.tagName).toBe('BUTTON')

    // No longer a line of body text pushing the input down.
    expect(document.body.textContent).not.toContain('Leave blank to use the')
  })

  it('defaults to notifying the buyer on a first post, and to silence on a correction', async () => {
    const unshipped = await mountWith([makeOrder({ status: 'confirmed' })])
    const vmA = unshipped.vm as unknown as Vm
    vmA.openShipment(vmA.orders[0]!)
    expect(vmA.shipmentDraft(vmA.orders[0]!).notify).toBe(true)

    clearNuxtData('admin-orders')
    const shipped = await mountWith([makeOrder({ status: 'shipped', shipped_at: '2026-09-01T00:00:00Z' })])
    const vmB = shipped.vm as unknown as Vm
    vmB.openShipment(vmB.orders[0]!)
    // The buyer has already been told once. Re-telling them is a choice, not
    // the default a mistyped digit drags along with it.
    expect(vmB.shipmentDraft(vmB.orders[0]!).notify).toBe(false)
  })

  it('records the shipment and closes the modal', async () => {
    const wrapper = await mountWith(
      [makeOrder({ status: 'confirmed' })],
      {
        order: {
          id: 'o1',
          courier: 'J&T Express',
          tracking_number: '630123456789',
          tracking_url: 'https://jt.example/630',
          shipped_at: '2026-09-10T00:00:00Z'
        },
        notified: { email: true, chat: true }
      }
    )
    const vm = wrapper.vm as unknown as Vm
    const order = vm.orders[0]!

    vm.openShipment(order)
    const draft = vm.shipmentDraft(order)
    draft.courier = 'J&T Express'
    draft.trackingNumber = '630123456789'
    await flushPromises()

    await vm.recordShipment(order)
    await flushPromises()

    expect(callMock).toHaveBeenCalledWith('/orders/o1/shipment', expect.objectContaining({ method: 'PUT' }))
    expect(order.status).toBe('shipped')
    expect(wrapper.findComponent({ name: 'UModal' }).props('open')).toBe(false)
  })

  it('keeps the modal open when the write is refused, so the draft is not lost', async () => {
    const wrapper = await mountWith([makeOrder({ status: 'confirmed' })])
    const vm = wrapper.vm as unknown as Vm
    const order = vm.orders[0]!

    vm.openShipment(order)
    const draft = vm.shipmentDraft(order)
    draft.courier = 'J&T Express'
    draft.trackingNumber = '630123456789'
    callMock.mockImplementationOnce(() => Promise.reject(new Error('nope')))

    await vm.recordShipment(order)
    await flushPromises()

    expect(wrapper.findComponent({ name: 'UModal' }).props('open')).toBe(true)
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ color: 'error' }))
  })

  it('keeps every other status transition, in the overflow menu', async () => {
    const wrapper = await mountWith([makeOrder({ status: 'shipped', shipped_at: '2026-09-01T00:00:00Z' })])

    const groups = wrapper.findComponent({ name: 'UDropdownMenu' }).props('items') as
      { label: string, onSelect?: () => void }[][]
    const items = groups.flat()

    const delivered = items.find(i => /delivered/i.test(i.label))
    expect(delivered, 'removing the select must not remove the capability').toBeTruthy()
    expect(items.some(i => /cancel/i.test(i.label))).toBe(true)
    expect(items.some(i => /refund/i.test(i.label))).toBe(true)
    expect(items.some(i => /delete/i.test(i.label))).toBe(true)

    delivered!.onSelect!()
    await flushPromises()

    expect(callMock).toHaveBeenCalledWith('/orders/o1/status', {
      method: 'PUT',
      body: { status: 'delivered' }
    })
  })

  it('shows the recorded tracking in the expanded row, read-only', async () => {
    const wrapper = await mountWith([makeOrder({
      status: 'shipped',
      courier: 'J&T Express',
      tracking_number: '630123456789',
      tracking_url: 'https://jt.example/630123456789',
      shipped_at: '2026-09-01T00:00:00Z'
    })])

    const expand = wrapper.findAll('button').find(b => b.html().includes('i-lucide:chevron-right'))
    await expand!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('630123456789')
    expect(wrapper.text()).toContain('J&T Express')
    // The form lives in the modal now; the row is a record, not an editor.
    expect(wrapper.findComponent({ name: 'UInputMenu' }).exists()).toBe(false)
  })
})
