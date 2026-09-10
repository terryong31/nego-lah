import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import AdminItems from '~/components/admin/AdminItems.vue'
import AdminOrders from '~/components/admin/AdminOrders.vue'
import AdminUsers from '~/components/admin/AdminUsers.vue'

/**
 * SPEC-065 — items, orders and users are three unbounded lists with no way to
 * find a row. Every one only grows: every listing ever created, every order ever
 * paid, every account ever registered.
 *
 * Filtering goes through `UTable`'s `global-filter` (TanStack's
 * `getFilteredRowModel`, which the component already wires) rather than a
 * client-side filter of the source array, so sorting and row expansion keep
 * working on the filtered set.
 */

const { callMock, toastAddMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn()
}))
mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

enableAutoUnmount(afterEach)

async function search(wrapper: { findComponent: (o: object) => { setValue: (v: string) => Promise<void> } }, term: string) {
  await wrapper.findComponent({ name: 'UInput' }).setValue(term)
  await flushPromises()
}

describe('console tables carry a search (SPEC-065)', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    clearNuxtData('admin-items')
    clearNuxtData('admin-orders')
    clearNuxtData('admin-users')
  })

  describe('items', () => {
    const items = [
      { id: 'i1', name: 'Apple AirPods Max', price: 1000, condition: 'good', status: 'available', created_at: '2026-01-01T00:00:00Z' },
      { id: 'i2', name: 'Casio VX-4', price: 200, condition: 'fair', status: 'sold', created_at: '2026-01-02T00:00:00Z' }
    ]

    beforeEach(() => {
      callMock.mockImplementation(() => Promise.resolve(items))
    })

    it('filters the rows and restores them when cleared', async () => {
      const wrapper = await mountSuspended(AdminItems)
      await flushPromises()
      expect(wrapper.text()).toContain('Apple AirPods Max')
      expect(wrapper.text()).toContain('Casio VX-4')

      await search(wrapper, 'casio')
      expect(wrapper.text()).not.toContain('Apple AirPods Max')
      expect(wrapper.text()).toContain('Casio VX-4')

      await search(wrapper, '')
      expect(wrapper.text()).toContain('Apple AirPods Max')
    })

    it('counts what is on screen, not what was fetched', async () => {
      const wrapper = await mountSuspended(AdminItems)
      await flushPromises()
      expect(wrapper.text()).toContain('2 item(s)')

      await search(wrapper, 'casio')
      // "2 item(s)" above a table showing one row is simply false.
      expect(wrapper.text()).toContain('1 item(s)')
    })
  })

  describe('orders', () => {
    const orders = [
      { id: 'o1', item_name: 'Apple AirPods Max', amount: 1000, status: 'confirmed', buyer_name: 'Alice', buyer_email: 'alice@example.com', created_at: '2026-01-01T00:00:00Z' },
      { id: 'o2', item_name: 'Casio VX-4', amount: 200, status: 'shipped', buyer_name: 'Bob', buyer_email: 'bob@example.com', created_at: '2026-01-02T00:00:00Z' }
    ]

    beforeEach(() => {
      callMock.mockImplementation((path: string) => {
        if (path === '/orders') {
          return Promise.resolve({ orders, stats: { total_orders: 2, total_sales: 1200 } })
        }
        return Promise.resolve({})
      })
    })

    it('filters by buyer as well as by item', async () => {
      const wrapper = await mountSuspended(AdminOrders)
      await flushPromises()

      await search(wrapper, 'Bob')
      expect(wrapper.text()).toContain('Casio VX-4')
      expect(wrapper.text()).not.toContain('Apple AirPods Max')
    })

    it('counts what is on screen', async () => {
      const wrapper = await mountSuspended(AdminOrders)
      await flushPromises()
      expect(wrapper.text()).toContain('2 order(s)')

      await search(wrapper, 'Bob')
      expect(wrapper.text()).toContain('1 order(s)')
    })

    it('says a query matched nothing, rather than looking empty', async () => {
      const wrapper = await mountSuspended(AdminOrders)
      await flushPromises()

      await search(wrapper, 'zzzz')
      expect(wrapper.text()).toContain('No orders match')
    })
  })

  describe('users', () => {
    const users = [
      { id: 'u1', email: 'alice@example.com', display_name: 'Alice', avatar_url: null, is_banned: false, ai_enabled: true, created_at: '2026-01-01T00:00:00Z' },
      { id: 'u2', email: 'bob@example.com', display_name: 'Bob', avatar_url: null, is_banned: false, ai_enabled: true, created_at: '2026-01-02T00:00:00Z' }
    ]

    beforeEach(() => {
      callMock.mockImplementation(() => Promise.resolve(users))
    })

    it('filters by display name', async () => {
      const wrapper = await mountSuspended(AdminUsers)
      await flushPromises()

      await search(wrapper, 'alice')
      expect(wrapper.text()).toContain('Alice')
      expect(wrapper.text()).not.toContain('Bob')
    })

    it('counts what is on screen', async () => {
      const wrapper = await mountSuspended(AdminUsers)
      await flushPromises()
      expect(wrapper.text()).toContain('2 user(s)')

      await search(wrapper, 'alice')
      expect(wrapper.text()).toContain('1 user(s)')
    })
  })
})
