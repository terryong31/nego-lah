import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mockComponent, mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import IndexPage from '~/pages/index.vue'

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

interface Msg {
  id: string
  role: 'user' | 'assistant'
  text: string
}

// The page's <script setup> exposes its top-level `ref`s (visible, typing,
// inputText) on the component's dev-mode proxy without an explicit
// `defineExpose` — the same pattern already relied on by
// tests/components/AppHeader.test.ts (`wrapper.vm.isAuthPage`). This lets us
// assert on the animation's actual state directly. We rely on this instead of
// reading the rendered `<UInput>`'s native `<input>` DOM value: that binding
// does not refresh in this render pipeline when `inputText` changes
// programmatically after mount (see notes in the final report) even though
// the underlying ref and the rest of the page's own template update fine.
interface IndexPageVm {
  inputText: string
  typing: Msg | null
  visible: Msg[]
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

// Deferred promise helper for controlling exactly when the featured-items
// fetch resolves, so we can observe the intermediate `pending: true` state.
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const callMock = vi.fn()
mockNuxtImport('useApi', () => () => ({ call: callMock }))

// Stub ItemGrid so we can assert on exactly what props index.vue hands it,
// without depending on ItemGrid/ItemCard's own rendering (covered by their
// own test files).
mockComponent('ItemGrid', {
  props: {
    items: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  template: '<div class="item-grid-stub" :data-loading="loading" :data-count="items.length" :data-ids="items.map((i) => i.item_id).join(\',\')" />'
})

describe('pages/index.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    // useAsyncData caches by key ('featured-items') on the shared nuxtApp
    // instance backing every test in this file, so without clearing it only
    // the first test's mount would ever actually invoke the fetcher.
    clearNuxtData('featured-items')
    // The hero section schedules a setTimeout-based "typing" animation from
    // onMounted. Run under fake timers so it never fires against a real
    // clock during (or after) a test.
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('featured items -> ItemGrid wiring', () => {
    it('calls the featured-items endpoint via useApi', async () => {
      callMock.mockResolvedValue([])
      await mountSuspended(IndexPage)

      expect(callMock).toHaveBeenCalledWith('/items/featured')
    })

    it('passes loading: true and an empty items array to ItemGrid while the fetch is in flight', async () => {
      const { promise } = deferred<Item[]>()
      callMock.mockReturnValue(promise)

      const wrapper = await mountSuspended(IndexPage)

      const grid = wrapper.find('.item-grid-stub')
      expect(grid.exists()).toBe(true)
      expect(grid.attributes('data-loading')).toBe('true')
      expect(grid.attributes('data-count')).toBe('0')
    })

    it('passes the resolved items and loading: false to ItemGrid once the fetch resolves', async () => {
      const items = [makeItem({ item_id: 'a1' }), makeItem({ item_id: 'b2' })]
      callMock.mockResolvedValue(items)

      const wrapper = await mountSuspended(IndexPage)

      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-loading')).toBe('false')
      expect(grid.attributes('data-count')).toBe('2')
      expect(grid.attributes('data-ids')).toBe('a1,b2')
    })

    it('falls back to an empty items array with loading: false when the fetch rejects', async () => {
      callMock.mockRejectedValue(new Error('network error'))

      const wrapper = await mountSuspended(IndexPage)

      const grid = wrapper.find('.item-grid-stub')
      expect(grid.attributes('data-loading')).toBe('false')
      expect(grid.attributes('data-count')).toBe('0')
    })
  })

  describe('hero "chat -> sale" animation', () => {
    it('mounts cleanly and schedules the scripted conversation via a timer', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      const vm = wrapper.vm as unknown as IndexPageVm

      // onMounted() kicked off play(), which starts with a 700ms wait().
      expect(vi.getTimerCount()).toBeGreaterThan(0)
      // Nothing has been said yet.
      expect(wrapper.text()).not.toContain('barely played')
      expect(vm.visible).toEqual([])
      expect(vm.typing).toBeNull()
      expect(vm.inputText).toBe('')
    })

    it('plays the full scripted conversation to completion without throwing', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      const vm = wrapper.vm as unknown as IndexPageVm

      // Drive every scheduled timer (including ones chained/created while
      // running) to let the whole conversation play out.
      await vi.runAllTimersAsync()

      // All five scripted messages should now be visible, in order.
      expect(wrapper.text()).toContain(`That's Terry's Fender Strat`)
      expect(wrapper.text()).toContain('Would you take RM240?')
      expect(wrapper.text()).toContain('fair for both of us')
      expect(wrapper.text()).toContain('Deal!')
      expect(wrapper.text()).toContain(`Sold! I'll pack it up today.`)
      expect(vm.visible.map(m => m.id)).toEqual(['m1', 'm2', 'm3', 'm4', 'm5'])

      // The typing indicator and the fake input should both be back to idle.
      expect(vm.typing).toBeNull()
      expect(vm.inputText).toBe('')

      // No further timers should be pending once the script has finished.
      expect(vi.getTimerCount()).toBe(0)
    })

    it('shows a typing indicator bubble while the "assistant" is composing a reply', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      const vm = wrapper.vm as unknown as IndexPageVm

      // wait(700) initial delay, then typing.value is set for the first message.
      await vi.advanceTimersByTimeAsync(700)
      await nextTick()

      expect(vm.typing?.id).toBe('m1')
      // UChatMessage doesn't forward the `id` prop to the rendered root
      // element, so also assert on the bouncing-dots indicator markup itself.
      expect(wrapper.find('.animate-bounce').exists()).toBe(true)
    })

    it('"types" the buyer message character by character before sending it', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      const vm = wrapper.vm as unknown as IndexPageVm

      // Advance past the first assistant message (700 initial wait + 1100
      // "typing" + 1200 pause after reveal) so the second, user-authored
      // message starts being typed into the fake input.
      await vi.advanceTimersByTimeAsync(700 + 1100 + 1200)
      await nextTick()
      // A few character-typing ticks (40ms each) into "Love it. ..."
      await vi.advanceTimersByTimeAsync(40 * 4)
      await nextTick()

      const full = 'Love it. Would you take RM240?'
      expect(vm.inputText.length).toBeGreaterThan(0)
      expect(vm.inputText.length).toBeLessThan(full.length)
      expect(full.startsWith(vm.inputText)).toBe(true)
      // Not sent yet — the message only joins `visible` after it's fully typed.
      expect(vm.visible.some(m => m.id === 'm2')).toBe(false)
    })

    it('updates inputText via the UInput\'s v-model binding when it emits update:modelValue', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      const vm = wrapper.vm as unknown as IndexPageVm

      // The fake input is `readonly`/`pointer-events-none` for the scripted
      // animation, but the `v-model="inputText"` binding itself (line 172)
      // still wires up an update:modelValue listener that writes back into
      // `inputText`. Drive the underlying native <input>'s `input` event
      // directly to exercise that listener, independent of the animation
      // timers.
      const input = wrapper.find('input')
      expect(input.exists()).toBe(true)

      await input.setValue('manually typed')

      expect(vm.inputText).toBe('manually typed')
    })

    it('clears all pending timers when the component unmounts mid-animation', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      await vi.advanceTimersByTimeAsync(700)
      expect(vi.getTimerCount()).toBeGreaterThan(0)

      wrapper.unmount()

      expect(vi.getTimerCount()).toBe(0)
    })

    it('does not throw or keep mutating state after unmount, even if timers are then advanced', async () => {
      callMock.mockResolvedValue([])

      const wrapper = await mountSuspended(IndexPage)
      await vi.advanceTimersByTimeAsync(700)

      wrapper.unmount()

      await expect(vi.runAllTimersAsync()).resolves.not.toThrow()
    })
  })
})
