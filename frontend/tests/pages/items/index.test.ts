import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { mockComponent, mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import ItemsIndexPage from '~/pages/items/index.vue'

interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string
  price?: number
  min_price?: number
  status?: string
}

// Shape of the <script setup> bindings exposed on wrapper.vm in this test
// harness - used purely to reach internals (searchInput, activeFilter) without `any`.
interface VmAny {
  searchInput: string
  activeFilter: 'all' | 'available' | 'sold'
}

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    item_id: 'item-1',
    name: 'Test Item',
    description: 'A test item',
    condition: 'new',
    images: '[]',
    price: 100,
    ...overrides
  }
}

// Deferred promise helper for controlling exactly when the /items fetch
// resolves, so we can observe the intermediate `pending: true` state.
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

const callMock = vi.fn()
mockNuxtImport('useApi', () => () => ({ call: callMock }))

// `route.query` is read on initial setup (to seed searchInput/debouncedSearch)
// and watched afterwards (to sync back when it changes externally, e.g. the
// browser back/forward buttons). It must be a real reactive object for that
// watch to fire when we mutate it from a test.
const routeStub = reactive<{ query: Record<string, string | undefined> }>({ query: {} })
mockNuxtImport('useRoute', () => () => routeStub)

// Note: useRouter is deliberately left un-mocked. A partial stub like
// `{ replace: vi.fn() }` breaks Nuxt's own internal client plugins
// (chunk-reload, navigation-repaint, ...) which call real router methods
// (`router.beforeEach`/`afterEach`/`beforeResolve`) during app init, e.g.
// "router.beforeEach is not a function". Instead we spy on the real router's
// `replace` method per-test via `wrapper.vm.$router`.
function spyOnRouterReplace(wrapper: { vm: { $router: { replace: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'replace').mockImplementation(() => Promise.resolve())
}

// Stub ItemGrid so we can assert on exactly what props index.vue hands it
// (including after client-side filtering), without depending on
// ItemGrid/ItemCard's own rendering (covered by their own test files).
mockComponent('ItemGrid', {
  props: {
    items: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  template: '<div class="item-grid-stub" :data-loading="loading" :data-count="items.length" :data-ids="items.map((i) => i.item_id).join(\',\')" />'
})

// Tracks the wrapper mounted by the current test so afterEach can dispose of
// it. `mountSuspended` doesn't auto-unmount the previous test's component -
// left alive, its watchers stay subscribed to the shared `routeStub` above,
// so mutating `routeStub.query` in a later test (even just resetting it in
// beforeEach) would otherwise re-trigger that stale instance's "sync search
// from route" watcher, which in turn re-triggers its debounce watcher and
// schedules a stray setTimeout on the *current* test's fake clock - polluting
// call counts on the shared `callMock`/router spies. Unmounting after every
// test avoids that cross-test leakage.
let activeWrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

async function mountPage() {
  activeWrapper = await mountSuspended(ItemsIndexPage)
  return activeWrapper
}

describe('pages/items/index.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    // useAsyncData caches by key ('items-listing') on the shared nuxtApp
    // instance backing every mountSuspended() call in this file, so without
    // clearing it only the first test's mount would ever actually invoke the
    // fetcher.
    clearNuxtData('items-listing')
    routeStub.query = {}
    vi.useFakeTimers()
  })

  afterEach(() => {
    activeWrapper?.unmount()
    activeWrapper = undefined
    vi.useRealTimers()
  })

  describe('initial fetch', () => {
    it('fetches /items with no keyword when the route has no keyword query param', async () => {
      callMock.mockResolvedValue([])
      await mountPage()

      expect(callMock).toHaveBeenCalledWith('/items')
    })

    it('fetches /items?keyword=... and seeds the search input when the route already has a keyword query param', async () => {
      routeStub.query = { keyword: 'guitar' }
      callMock.mockResolvedValue([])

      const wrapper = await mountPage()

      expect(callMock).toHaveBeenCalledWith('/items?keyword=guitar')
      expect((wrapper.vm as VmAny).searchInput).toBe('guitar')
    })

    it('URL-encodes special characters in the initial keyword', async () => {
      routeStub.query = { keyword: 'foo bar&baz' }
      callMock.mockResolvedValue([])

      await mountPage()

      expect(callMock).toHaveBeenCalledWith(`/items?keyword=${encodeURIComponent('foo bar&baz')}`)
    })

    it('passes loading: true and an empty items array to ItemGrid while the fetch is in flight', async () => {
      const { promise } = deferred<Item[]>()
      callMock.mockReturnValue(promise)

      const wrapper = await mountPage()

      const grid = wrapper.find('.item-grid-stub')
      expect(grid.exists()).toBe(true)
      expect(grid.attributes('data-loading')).toBe('true')
      expect(grid.attributes('data-count')).toBe('0')
    })

    it('passes the resolved items and loading: false to ItemGrid once the fetch resolves', async () => {
      const items = [makeItem({ item_id: 'a1' }), makeItem({ item_id: 'b2' })]
      callMock.mockResolvedValue(items)

      const wrapper = await mountPage()

      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-loading')).toBe('false')
      expect(grid.attributes('data-count')).toBe('2')
      expect(grid.attributes('data-ids')).toBe('a1,b2')
    })

    it('falls back to an empty items array with loading: false when the fetch rejects', async () => {
      callMock.mockRejectedValue(new Error('network error'))

      const wrapper = await mountPage()

      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-loading')).toBe('false')
      expect(grid.attributes('data-count')).toBe('0')
    })
  })

  describe('search debounce -> route sync', () => {
    it('does not update the route or refetch immediately when typing', async () => {
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      const replaceSpy = spyOnRouterReplace(wrapper)
      callMock.mockClear()

      await wrapper.find('input').setValue('lamp')

      expect(replaceSpy).not.toHaveBeenCalled()
      expect(callMock).not.toHaveBeenCalled()
    })

    it('still has not fired 349ms after typing stops', async () => {
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      const replaceSpy = spyOnRouterReplace(wrapper)
      callMock.mockClear()

      await wrapper.find('input').setValue('lamp')
      await vi.advanceTimersByTimeAsync(349)

      expect(replaceSpy).not.toHaveBeenCalled()
      expect(callMock).not.toHaveBeenCalled()
    })

    it('updates route.query.keyword and refetches with the keyword 350ms after typing stops', async () => {
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      const replaceSpy = spyOnRouterReplace(wrapper)
      callMock.mockClear()

      await wrapper.find('input').setValue('lamp')
      await vi.advanceTimersByTimeAsync(350)

      expect(replaceSpy).toHaveBeenCalledWith({ query: { keyword: 'lamp' } })
      expect(callMock).toHaveBeenCalledWith('/items?keyword=lamp')
    })

    it('preserves other existing route query params when replacing', async () => {
      routeStub.query = { sort: 'newest' }
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      const replaceSpy = spyOnRouterReplace(wrapper)
      callMock.mockClear()
      replaceSpy.mockClear()

      await wrapper.find('input').setValue('lamp')
      await vi.advanceTimersByTimeAsync(350)

      expect(replaceSpy).toHaveBeenCalledWith({ query: { sort: 'newest', keyword: 'lamp' } })
    })

    it('replaces the route with keyword: undefined (dropping the param) when the search is cleared', async () => {
      routeStub.query = { keyword: 'lamp' }
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      const replaceSpy = spyOnRouterReplace(wrapper)
      callMock.mockClear()
      replaceSpy.mockClear()

      await wrapper.find('input').setValue('')
      await vi.advanceTimersByTimeAsync(350)

      expect(replaceSpy).toHaveBeenCalledWith({ query: { keyword: undefined } })
      expect(callMock).toHaveBeenCalledWith('/items')
    })

    it('BUG: the watch callback\'s returned cleanup function is a no-op (Vue only honors `onCleanup`), so rapid keystrokes each schedule an independent timer instead of truly debouncing', async () => {
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      const replaceSpy = spyOnRouterReplace(wrapper)
      callMock.mockClear()
      replaceSpy.mockClear()

      const input = wrapper.find('input')
      await input.setValue('l')
      await input.setValue('la')
      await input.setValue('lamp')

      await vi.advanceTimersByTimeAsync(350)

      // If the debounce worked as intended, only the final value would ever
      // reach the route/API - exactly one call. Instead every keystroke's
      // timer survives (the returned `() => clearTimeout(timeout)` is never
      // actually invoked by Vue - `watch()` only honors a real `onCleanup`
      // callback, not a plain return value) and fires independently.
      expect(replaceSpy).toHaveBeenCalledTimes(3)
      expect(replaceSpy).toHaveBeenNthCalledWith(1, { query: { keyword: 'l' } })
      expect(replaceSpy).toHaveBeenNthCalledWith(2, { query: { keyword: 'la' } })
      expect(replaceSpy).toHaveBeenNthCalledWith(3, { query: { keyword: 'lamp' } })

      // The final debounced value is still correct, so functionally the search
      // box "works" for a human typing - the bug is the redundant network
      // traffic / route replacements it causes along the way.
      expect((wrapper.vm as VmAny).searchInput).toBe('lamp')
    })
  })

  describe('external route changes (e.g. browser back/forward)', () => {
    it('syncs the search input and refetches when route.query.keyword changes externally', async () => {
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      callMock.mockClear()

      routeStub.query.keyword = 'sofa'
      await nextTick()

      expect((wrapper.vm as VmAny).searchInput).toBe('sofa')
      expect(callMock).toHaveBeenCalledWith('/items?keyword=sofa')
    })

    it('clears the search input when route.query.keyword is externally removed', async () => {
      routeStub.query = { keyword: 'sofa' }
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()
      callMock.mockClear()

      delete routeStub.query.keyword
      await nextTick()

      expect((wrapper.vm as VmAny).searchInput).toBe('')
      expect(callMock).toHaveBeenCalledWith('/items')
    })
  })

  describe('activeFilter client-side filtering', () => {
    const items = [
      makeItem({ item_id: 'a1', name: 'Available Item', status: 'available' }),
      makeItem({ item_id: 'b2', name: 'Sold Item', status: 'sold' }),
      makeItem({ item_id: 'c3', name: 'No Status Item', status: undefined })
    ]

    async function mountWithItems() {
      callMock.mockResolvedValue(items)
      return mountPage()
    }

    function filterButtons(wrapper: Awaited<ReturnType<typeof mountWithItems>>) {
      const buttons = wrapper.findAll('button')
      return {
        all: buttons.find(b => b.text() === 'All')!,
        available: buttons.find(b => b.text() === 'Available')!,
        sold: buttons.find(b => b.text() === 'Sold Out')!
      }
    }

    it('defaults to "all" and shows every item regardless of status', async () => {
      const wrapper = await mountWithItems()

      expect((wrapper.vm as VmAny).activeFilter).toBe('all')
      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-count')).toBe('3')
      expect(grid.attributes('data-ids')).toBe('a1,b2,c3')
    })

    it('"Available" filters out items whose status is "sold" (keeps missing/other statuses)', async () => {
      const wrapper = await mountWithItems()
      const { available } = filterButtons(wrapper)

      await available.trigger('click')

      expect((wrapper.vm as VmAny).activeFilter).toBe('available')
      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-ids')).toBe('a1,c3')
    })

    it('"Sold Out" shows only items whose status is "sold"', async () => {
      const wrapper = await mountWithItems()
      const { sold } = filterButtons(wrapper)

      await sold.trigger('click')

      expect((wrapper.vm as VmAny).activeFilter).toBe('sold')
      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-ids')).toBe('b2')
    })

    it('switching back to "All" restores the full unfiltered list', async () => {
      const wrapper = await mountWithItems()
      const { all, sold } = filterButtons(wrapper)

      await sold.trigger('click')
      expect(wrapper.find('.item-grid-stub').attributes('data-ids')).toBe('b2')

      await all.trigger('click')
      expect((wrapper.vm as VmAny).activeFilter).toBe('all')
      expect(wrapper.find('.item-grid-stub').attributes('data-ids')).toBe('a1,b2,c3')
    })

    it('renders exactly one "All"/"Available"/"Sold Out" filter pill each', async () => {
      const wrapper = await mountWithItems()
      const { all, available, sold } = filterButtons(wrapper)

      expect(all.exists()).toBe(true)
      expect(available.exists()).toBe(true)
      expect(sold.exists()).toBe(true)
    })
  })

  describe('page metadata', () => {
    it('renders the page heading and description copy', async () => {
      callMock.mockResolvedValue([])
      const wrapper = await mountPage()

      expect(wrapper.find('h1').text()).toBe('All Items')
      expect(wrapper.text()).toContain('Browse every listing and start a bargain session.')
    })
  })
})
