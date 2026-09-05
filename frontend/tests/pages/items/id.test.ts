import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import ItemDetailPage from '~/pages/items/[id].vue'

interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string
  price?: number
  min_price?: number
  status?: string
  translations?: Record<string, { name?: string, description?: string, condition?: string }>
}

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    item_id: 'item-1',
    name: 'Vintage Camera',
    description: 'A nice old camera',
    condition: 'Used - Good',
    images: '["/img/a.jpg", "/img/b.jpg"]',
    price: 123.4,
    min_price: 100,
    status: 'available',
    ...overrides
  }
}

// Deferred promise helper for controlling exactly when a fetch resolves, so we
// can observe intermediate `pending`/`buyLoading` states.
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const { userRef } = vi.hoisted(() => ({
  userRef: { __v_isRef: true, value: null as Record<string, unknown> | null }
}))
const { navigateToMock, toastAddMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn(),
  toastAddMock: vi.fn()
}))

const callMock = vi.fn()

mockNuxtImport('useApi', () => () => ({ call: callMock }))
mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('navigateTo', () => navigateToMock)
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

async function mountAtItem(id = 'item-1') {
  return mountSuspended(ItemDetailPage, { route: `/items/${id}` })
}

describe('pages/items/[id].vue', () => {
  beforeEach(() => {
    userRef.value = null
    callMock.mockReset()
    navigateToMock.mockClear()
    toastAddMock.mockClear()
    // useAsyncData caches by key (`item-detail-<id>`) on the shared nuxtApp
    // instance backing every test in this file, so without clearing it only
    // the first test to use a given id would ever actually invoke the fetcher.
    clearNuxtData()
  })

  describe('loading / error / not-found states', () => {
    it('shows the loading skeleton while the item fetch is in flight', async () => {
      const { promise } = deferred<Item>()
      callMock.mockReturnValue(promise)

      const wrapper = await mountAtItem()

      expect(wrapper.findComponent({ name: 'USkeleton' }).exists()).toBe(true)
      expect(wrapper.text()).not.toContain('Item Not Found')
      expect(wrapper.text()).not.toContain('Vintage Camera')
    })

    it('shows the "Item Not Found" state when the fetch rejects', async () => {
      callMock.mockRejectedValue(Object.assign(new Error('not found'), { statusCode: 404 }))

      const wrapper = await mountAtItem()

      expect(wrapper.text()).toContain('Item Not Found')
      expect(wrapper.text()).toContain('The listing might have been removed or deleted.')
      expect(wrapper.findComponent({ name: 'UButton' }).props('to')).toBe('/')
    })
  })

  describe('successful render', () => {
    it('renders the item name, price, condition and description', async () => {
      callMock.mockResolvedValue(makeItem({ name: 'Vintage Camera', price: 123.4, condition: 'Used - Good' }))

      const wrapper = await mountAtItem()

      expect(wrapper.find('h1').text()).toBe('Vintage Camera')
      expect(wrapper.text()).toContain('RM 123.40')
      expect(wrapper.text()).toContain('Used - Good')
    })

    it('calls the item-detail endpoint for the id in the route', async () => {
      callMock.mockResolvedValue(makeItem())

      await mountAtItem('abc-123')

      expect(callMock).toHaveBeenCalledWith('/items/abc-123')
    })

    it('renders localized title and condition when translation is available for the current locale', async () => {
      callMock.mockResolvedValue(makeItem({
        name: 'Vintage Camera',
        condition: 'Used - Good',
        translations: {
          en: { name: 'Vintage Camera (EN)', condition: 'Used - Mint' }
        }
      }))

      const wrapper = await mountAtItem()

      expect(wrapper.find('h1').text()).toBe('Vintage Camera (EN)')
      expect(wrapper.text()).toContain('Used - Mint')
    })

    it('falls back to default item name and condition when translation is not available', async () => {
      callMock.mockResolvedValue(makeItem({
        name: 'Vintage Camera',
        condition: 'Used - Good',
        translations: {}
      }))

      const wrapper = await mountAtItem()

      expect(wrapper.find('h1').text()).toBe('Vintage Camera')
      expect(wrapper.text()).toContain('Used - Good')
    })
  })

  describe('imagesList (JSON-parse-then-comma-fallback, matching ItemCard)', () => {
    it('uses the full array when images is valid JSON', async () => {
      callMock.mockResolvedValue(makeItem({ images: '["/img/a.jpg", "/img/b.jpg", "/img/c.jpg"]' }))

      const wrapper = await mountAtItem()

      expect(wrapper.vm.imagesList).toEqual(['/img/a.jpg', '/img/b.jpg', '/img/c.jpg'])
      const imgs = wrapper.findAll('img')
      expect(imgs).toHaveLength(3)
      expect(imgs.map(img => img.attributes('src'))).toEqual(['/img/a.jpg', '/img/b.jpg', '/img/c.jpg'])
    })

    it('falls back to comma-splitting (and trims) when images is not valid JSON', async () => {
      callMock.mockResolvedValue(makeItem({ images: '/img/c.jpg, /img/d.jpg' }))

      const wrapper = await mountAtItem()

      expect(wrapper.vm.imagesList).toEqual(['/img/c.jpg', '/img/d.jpg'])
    })

    it('uses the raw string as an ultimate fallback for a bare string with no commas', async () => {
      callMock.mockResolvedValue(makeItem({ images: '/img/single.jpg' }))

      const wrapper = await mountAtItem()

      expect(wrapper.vm.imagesList).toEqual(['/img/single.jpg'])
      expect(wrapper.find('img').attributes('src')).toBe('/img/single.jpg')
    })

    it('shows "No Images Available" and no carousel when the item has no images', async () => {
      callMock.mockResolvedValue(makeItem({ images: '' }))

      const wrapper = await mountAtItem()

      expect(wrapper.vm.imagesList).toEqual([])
      expect(wrapper.text()).toContain('No Images Available')
      expect(wrapper.find('img').exists()).toBe(false)
    })

    it('a JSON value that parses but is not an array falls back to the comma-split branch', async () => {
      // JSON.parse('{"a":1}') succeeds but Array.isArray is false, so the code
      // falls through to `return [item.value.images]` (not the catch block).
      callMock.mockResolvedValue(makeItem({ images: '{"a":1}' }))

      const wrapper = await mountAtItem()

      expect(wrapper.vm.imagesList).toEqual(['{"a":1}'])
    })
  })

  describe('sold item UI', () => {
    it('shows the "Item Sold" alert and hides the Buy Now / Negotiate buttons when status is sold', async () => {
      callMock.mockResolvedValue(makeItem({ status: 'sold' }))

      const wrapper = await mountAtItem()

      expect(wrapper.text()).toContain('Item Sold')
      expect(wrapper.text()).not.toContain('Buy Now')
      expect(wrapper.text()).not.toContain('Negotiate Price')
    })

    it('shows the Buy Now / Negotiate buttons and no sold alert when status is not sold', async () => {
      callMock.mockResolvedValue(makeItem({ status: 'available' }))

      const wrapper = await mountAtItem()

      expect(wrapper.text()).not.toContain('Item Sold')
      expect(wrapper.text()).toContain('Buy Now')
      expect(wrapper.text()).toContain('Negotiate Price')
    })
  })

  describe('Negotiate Price link target', () => {
    it('points at /login with redirect query when logged out', async () => {
      userRef.value = null
      callMock.mockResolvedValue(makeItem({ item_id: 'item-1' }))

      const wrapper = await mountAtItem()
      const buttons = wrapper.findAllComponents({ name: 'UButton' })
      const negotiate = buttons.find(b => b.text().includes('Negotiate Price'))

      expect(negotiate?.props('to')).toEqual({
        path: '/login',
        query: { redirect: '/chat?item_id=item-1' }
      })
    })

    it('points at /chat?item_id=<id> when logged in', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      callMock.mockResolvedValue(makeItem({ item_id: 'item-1' }))

      const wrapper = await mountAtItem()
      const buttons = wrapper.findAllComponents({ name: 'UButton' })
      const negotiate = buttons.find(b => b.text().includes('Negotiate Price'))

      expect(negotiate?.props('to')).toBe('/chat?item_id=item-1')
    })
  })

  describe('handleBuyNow', () => {
    it('redirects to /login and never calls the checkout endpoint when logged out', async () => {
      userRef.value = null
      callMock.mockResolvedValue(makeItem())

      const wrapper = await mountAtItem()
      callMock.mockClear() // clear the initial item-fetch call so we can assert on checkout calls only

      await wrapper.vm.handleBuyNow()

      expect(navigateToMock).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/items/item-1' }
      })
      expect(callMock).not.toHaveBeenCalled()
    })

    it('redirects the browser to the checkout URL on a successful response', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1' })
      callMock.mockImplementation((path: string) => {
        if (path === '/items/item-1') return Promise.resolve(item)
        return Promise.resolve({ checkout_url: 'https://checkout.stripe.com/session/abc' })
      })

      const wrapper = await mountAtItem()

      const originalLocation = window.location
      // @ts-expect-error - deliberately deleting to allow a plain, settable stand-in
      delete window.location
      window.location = { href: '' } as unknown as Location

      try {
        await wrapper.vm.handleBuyNow()

        expect(callMock).toHaveBeenCalledWith('/payment/checkout', {
          method: 'POST',
          body: { item_id: 'item-1', user_id: 'u1' }
        })
        expect(toastAddMock).toHaveBeenCalledWith({
          title: 'Redirecting to checkout',
          description: 'Opening Stripe billing screen...',
          color: 'success'
        })
        expect(window.location.href).toBe('https://checkout.stripe.com/session/abc')
      } finally {
        window.location = originalLocation
      }
    })

    it('shows a "no longer available" toast and refreshes the item on a 409 response', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1', status: 'available' })
      const soldItem = { ...item, status: 'sold' }

      callMock.mockImplementationOnce(() => Promise.resolve(item)) // initial item fetch
      const wrapper = await mountAtItem()

      callMock.mockImplementationOnce(() => Promise.reject(Object.assign(new Error('Conflict'), { statusCode: 409 })))
      callMock.mockImplementationOnce(() => Promise.resolve(soldItem)) // refresh() refetch

      await wrapper.vm.handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'No longer available',
        description: 'Sorry, this item has just been sold.',
        color: 'warning'
      })
      // refresh() re-ran the fetcher, updating the page to the sold state.
      expect(callMock).toHaveBeenCalledTimes(3)
      await flushPromises()
      expect(wrapper.text()).toContain('Item Sold')
    })

    it('also treats a bare `status` (rather than `statusCode`) of 409 as "sold"', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1' })

      callMock.mockImplementationOnce(() => Promise.resolve(item))
      const wrapper = await mountAtItem()

      callMock.mockImplementationOnce(() => Promise.reject(Object.assign(new Error('Conflict'), { status: 409 })))
      callMock.mockImplementationOnce(() => Promise.resolve(item))

      await wrapper.vm.handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'No longer available',
        description: 'Sorry, this item has just been sold.',
        color: 'warning'
      })
    })

    it('shows a generic error toast for a non-409 failure and does not refresh', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1' })

      callMock.mockImplementationOnce(() => Promise.resolve(item))
      const wrapper = await mountAtItem()

      callMock.mockImplementationOnce(() => Promise.reject(new Error('Card declined')))

      await wrapper.vm.handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Checkout failed',
        description: 'Card declined',
        color: 'error'
      })
      // Only the initial fetch + the failed checkout call — no refresh-triggered refetch.
      expect(callMock).toHaveBeenCalledTimes(2)
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1' })

      callMock.mockImplementationOnce(() => Promise.resolve(item))
      const wrapper = await mountAtItem()

      callMock.mockImplementationOnce(() => Promise.reject('a plain string rejection'))

      await wrapper.vm.handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Checkout failed',
        description: 'Unable to start transaction',
        color: 'error'
      })
    })

    it('throws (surfaced as a generic checkout-failed toast) when the response has no checkout_url', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1' })

      callMock.mockImplementationOnce(() => Promise.resolve(item))
      const wrapper = await mountAtItem()

      callMock.mockImplementationOnce(() => Promise.resolve({}))

      await wrapper.vm.handleBuyNow()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Checkout failed',
        description: 'No checkout URL returned',
        color: 'error'
      })
    })

    it('sets buyLoading true while the checkout call is in flight and false afterwards', async () => {
      userRef.value = { id: 'u1', email: 'a@b.com' }
      const item = makeItem({ item_id: 'item-1' })
      callMock.mockImplementationOnce(() => Promise.resolve(item))
      const wrapper = await mountAtItem()

      const { promise, resolve } = deferred<{ checkout_url?: string }>()
      callMock.mockImplementationOnce(() => promise)

      const originalLocation = window.location
      // @ts-expect-error - deliberately deleting to allow a plain, settable stand-in
      delete window.location
      window.location = { href: '' } as unknown as Location

      try {
        const call = wrapper.vm.handleBuyNow()
        await flushPromises()
        expect(wrapper.vm.buyLoading).toBe(true)

        resolve({ checkout_url: 'https://checkout.stripe.com/session/xyz' })
        await call

        expect(wrapper.vm.buyLoading).toBe(false)
      } finally {
        window.location = originalLocation
      }
    })

    it('clicking the Buy Now button while logged out triggers the /login redirect end-to-end', async () => {
      userRef.value = null
      callMock.mockResolvedValue(makeItem())

      const wrapper = await mountAtItem()
      const buttons = wrapper.findAllComponents({ name: 'UButton' })
      const buyNow = buttons.find(b => b.text().includes('Buy Now'))

      await buyNow?.trigger('click')
      await flushPromises()

      expect(navigateToMock).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/items/item-1' }
      })
    })

    it('renders strikethrough price and the discount percentage badge when discounted_price is present', async () => {
      callMock.mockResolvedValue(makeItem({
        price: 200,
        discounted_price: 150
      }))

      const wrapper = await mountAtItem()

      expect(wrapper.text()).toContain('RM 150.00')
      expect(wrapper.text()).toContain('RM 200.00')
      expect(wrapper.text()).toContain('-25%')
      expect(wrapper.find('.line-through').text()).toContain('RM 200.00')
    })

    it('shows only the listed price when the discount is not below it', async () => {
      callMock.mockResolvedValue(makeItem({
        price: 200,
        discounted_price: 200
      }))

      const wrapper = await mountAtItem()

      expect(wrapper.text()).toContain('RM 200.00')
      expect(wrapper.text()).not.toContain('%')
      expect(wrapper.find('.line-through').exists()).toBe(false)
    })
  })
})
