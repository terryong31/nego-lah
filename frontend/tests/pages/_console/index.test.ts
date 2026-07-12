import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import type { VueWrapper } from '@vue/test-utils'
import AdminDashboardPage from '~/pages/_console/index.vue'

interface Summary {
  users: number
  conversations: number
  items_total: number
  items_available: number
  items_sold: number
  orders_total: number
  orders_pending: number
  orders_confirmed: number
  orders_shipped: number
  orders_delivered: number
  sales_total: number
}

function makeSummary(overrides: Partial<Summary> = {}): Summary {
  return {
    users: 12,
    conversations: 5,
    items_total: 40,
    items_available: 30,
    items_sold: 10,
    orders_total: 22,
    orders_pending: 3,
    orders_confirmed: 4,
    orders_shipped: 2,
    orders_delivered: 13,
    sales_total: 1234.5,
    ...overrides
  }
}

// Mirrors the page's own `money()` formula so assertions don't hardcode a
// locale-specific string that could drift from the environment's ICU data.
const money = (n: number) => `RM ${(n || 0).toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Deferred promise helper for controlling exactly when the /summary fetch
// resolves, so we can observe the intermediate `pending: true` state.
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

const { callMock, navigateToMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  navigateToMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('navigateTo', () => navigateToMock)

let wrapper: VueWrapper | undefined

async function mountPage() {
  wrapper = await mountSuspended(AdminDashboardPage)
  return wrapper
}

// Every UCard in this page renders `data-slot="root"` on its outer element
// (see @nuxt/ui's Card.vue), but so do several *ancestor* components on this
// page (UDashboardPanel, UDashboardNavbar) - a plain `[data-slot="root"]`
// selector would match those too, and since they wrap the whole page their
// `.text()` also "contains" every card's label. Card.vue's root uniquely
// carries the `rounded-lg` utility class (from its theme), so combining both
// narrows the match down to actual card elements only.
function findCard(w: VueWrapper, label: string) {
  const card = w.findAll('[data-slot="root"].rounded-lg').find(c => c.text().includes(label))
  if (!card) throw new Error(`card not found for label: ${label}`)
  return card
}

describe('pages/_console/index.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    navigateToMock.mockClear()
    // useAsyncData caches by key ('admin-summary') on the shared nuxtApp
    // instance backing every mountSuspended() call in this file, so without
    // clearing it only the first test's mount would ever actually invoke the
    // fetcher.
    clearNuxtData('admin-summary')
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  describe('initial fetch', () => {
    it('calls /summary on mount', async () => {
      callMock.mockResolvedValue(makeSummary())
      await mountPage()

      expect(callMock).toHaveBeenCalledWith('/summary')
    })

    it('shows a skeleton placeholder in every card while the fetch is in flight, and none once it resolves', async () => {
      const { promise, resolve } = deferred<Summary>()
      callMock.mockReturnValue(promise)

      const w = await mountPage()

      // 4 headline stats + 4 pipeline stages + 3 inventory tiles = 11 cards,
      // each rendering exactly one USkeleton (aria-busy="true") while pending.
      expect(w.findAll('[aria-busy="true"]')).toHaveLength(11)
      expect(w.text()).not.toContain('RM 0.00')

      resolve(makeSummary())
      await vi.waitFor(() => {
        expect(w.findAll('[aria-busy="true"]')).toHaveLength(0)
      })
    })

    it('falls back to zeroed defaults when the fetch rejects', async () => {
      callMock.mockRejectedValue(new Error('network down'))
      const w = await mountPage()

      expect(findCard(w, 'Total sales').text()).toContain(money(0))
      expect(findCard(w, 'Orders').text()).toContain('0')
      expect(findCard(w, 'Users').text()).toContain('0')
      expect(findCard(w, 'Active chats').text()).toContain('0')
      expect(w.text()).not.toContain('undefined')
      expect(w.text()).not.toContain('NaN')
    })
  })

  describe('money() formatting', () => {
    it('formats sales_total as an RM-prefixed string with thousands separators and 2 decimals', async () => {
      callMock.mockResolvedValue(makeSummary({ sales_total: 1234.5 }))
      const w = await mountPage()

      expect(money(1234.5)).toBe('RM 1,234.50')
      expect(findCard(w, 'Total sales').text()).toContain('RM 1,234.50')
    })

    it('formats a zero sales_total as "RM 0.00"', async () => {
      callMock.mockResolvedValue(makeSummary({ sales_total: 0 }))
      const w = await mountPage()

      expect(findCard(w, 'Total sales').text()).toContain('RM 0.00')
    })

    it('formats a large sales_total with multiple thousands separators', async () => {
      callMock.mockResolvedValue(makeSummary({ sales_total: 1234567.89 }))
      const w = await mountPage()

      expect(findCard(w, 'Total sales').text()).toContain(money(1234567.89))
      expect(findCard(w, 'Total sales').text()).toContain('1,234,567.89')
    })
  })

  describe('headline stats cards', () => {
    it('renders Orders, Users, and Active chats as plain (non-money) numbers', async () => {
      const summary = makeSummary({ orders_total: 22, users: 12, conversations: 5 })
      callMock.mockResolvedValue(summary)
      const w = await mountPage()

      expect(findCard(w, 'Orders').text()).toContain('22')
      expect(findCard(w, 'Users').text()).toContain('12')
      expect(findCard(w, 'Active chats').text()).toContain('5')
    })
  })

  describe('orders pipeline (attention) cards', () => {
    it('renders orders_pending under "Awaiting shipping info"', async () => {
      callMock.mockResolvedValue(makeSummary({ orders_pending: 7 }))
      const w = await mountPage()

      expect(findCard(w, 'Awaiting shipping info').text()).toContain('7')
    })

    it('renders orders_confirmed under "Ready to ship"', async () => {
      callMock.mockResolvedValue(makeSummary({ orders_confirmed: 9 }))
      const w = await mountPage()

      expect(findCard(w, 'Ready to ship').text()).toContain('9')
    })

    it('renders orders_shipped under "Shipped"', async () => {
      callMock.mockResolvedValue(makeSummary({ orders_shipped: 6 }))
      const w = await mountPage()

      expect(findCard(w, 'Shipped').text()).toContain('6')
    })

    it('renders orders_delivered under "Delivered"', async () => {
      callMock.mockResolvedValue(makeSummary({ orders_delivered: 41 }))
      const w = await mountPage()

      expect(findCard(w, 'Delivered').text()).toContain('41')
    })
  })

  describe('inventory cards', () => {
    it('renders items_total under "Listings"', async () => {
      callMock.mockResolvedValue(makeSummary({ items_total: 88 }))
      const w = await mountPage()

      expect(findCard(w, 'Listings').text()).toContain('88')
    })

    it('renders items_available under "Available"', async () => {
      callMock.mockResolvedValue(makeSummary({ items_available: 55 }))
      const w = await mountPage()

      expect(findCard(w, 'Available').text()).toContain('55')
    })

    it('renders items_sold under "Sold"', async () => {
      callMock.mockResolvedValue(makeSummary({ items_sold: 33 }))
      const w = await mountPage()

      expect(findCard(w, 'Sold').text()).toContain('33')
    })
  })

  describe('clickable stat card navigation', () => {
    it('navigates to /_console/orders when the Orders card is clicked', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      await findCard(w, 'Orders').trigger('click')

      expect(navigateToMock).toHaveBeenCalledWith('/_console/orders')
    })

    it('navigates to /_console/users when the Users card is clicked', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      await findCard(w, 'Users').trigger('click')

      expect(navigateToMock).toHaveBeenCalledWith('/_console/users')
    })

    it('navigates to /_console/chats when the Active chats card is clicked', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      await findCard(w, 'Active chats').trigger('click')

      expect(navigateToMock).toHaveBeenCalledWith('/_console/chats')
    })

    it('does NOT navigate when the non-clickable Total sales card is clicked', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      await findCard(w, 'Total sales').trigger('click')

      expect(navigateToMock).not.toHaveBeenCalled()
    })

    it('applies the cursor-pointer affordance class only to cards with a destination', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      expect(findCard(w, 'Orders').classes()).toContain('cursor-pointer')
      expect(findCard(w, 'Total sales').classes()).not.toContain('cursor-pointer')
    })
  })

  describe('refresh button', () => {
    it('refetches /summary when the Refresh button is clicked', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()
      callMock.mockClear()
      callMock.mockResolvedValue(makeSummary({ users: 99 }))

      const refreshButton = w.findAll('button').find(b => b.text().includes('Refresh'))
      expect(refreshButton).toBeTruthy()

      await refreshButton!.trigger('click')
      await vi.waitFor(() => {
        expect(callMock).toHaveBeenCalledWith('/summary')
      })

      expect(findCard(w, 'Users').text()).toContain('99')
    })
  })

  describe('page metadata', () => {
    it('renders the dashboard navbar title', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      expect(w.text()).toContain('Dashboard')
    })

    it('renders the "Orders pipeline" and "Inventory" section headings', async () => {
      callMock.mockResolvedValue(makeSummary())
      const w = await mountPage()

      expect(w.text()).toContain('Orders pipeline')
      expect(w.text()).toContain('Inventory')
    })
  })
})
