import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import AdminItems from '~/components/admin/AdminItems.vue'

const { callMock, toastAddMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

interface Item {
  id: string
  name: string
  description: string
  condition: string
  price: number
  min_price: number | null
  image_path: string | null
  status: string
  created_at: string
}

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: 'item-1',
    name: 'Vintage Chair',
    description: 'A comfy chair',
    condition: 'Good',
    price: 120,
    min_price: null,
    image_path: null,
    status: 'available',
    created_at: '2026-01-15T00:00:00Z',
    ...overrides
  }
}

function makeFile(name = 'photo.png'): File {
  return new File(['fake-bytes'], name, { type: 'image/png' })
}

// <UModal> teleports its #body/#footer content via Reka UI's Portal, which in
// this harness has no attached teleport target - mountSuspended()'s wrapper
// tree is never attached to the real `document`, so Vue's <Teleport> silently
// declines to render its children at all (confirmed empirically: components
// inside the modal body/footer, e.g. UFileUpload, never even reach setup()).
// This matches the documented limitation in tests/pages/profile.test.ts for
// the same UModal-based pattern. Stubbing UModal out for a small, local set of
// DOM-level tests - rendering its #body/#footer slots inline behind its `open`
// prop instead of teleporting them - lets us exercise the real (unstubbed)
// UFormField/UInput/UFileUpload/etc. fields and the footer buttons directly.
const UModalStub = {
  name: 'UModalStub',
  props: ['open'],
  emits: ['update:open'],
  template: '<div><slot v-if="open" name="body" /><slot v-if="open" name="footer" /></div>'
}

// Shape of the <script setup> bindings exposed on wrapper.vm in this test harness -
// used purely to reach internals without `any` everywhere.
interface VmAny {
  items: Item[]
  pending: boolean
  open: boolean
  saving: boolean
  editingId: string | null
  isEditing: boolean
  form: {
    name: string
    description: string
    condition: string
    price: number | undefined
    min_price: number | undefined
  }
  files: File[]
  isAnalyzing: boolean
  progress: number
  busy: string | null
  canSubmit: boolean
  openCreate: () => void
  openEdit: (item: Item) => void
  submitItem: () => Promise<void>
  remove: (item: Item) => Promise<void>
  firstImage: (item: Item) => string | undefined
  formatDate: (d: string) => string
}

describe('components/admin/AdminItems.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    // useAsyncData('admin-items', ...) caches its result on the shared nuxtApp
    // instance that backs every mountSuspended() call in this file, so without
    // clearing it, only the very first test's mount would ever actually
    // invoke the fetcher.
    clearNuxtData('admin-items')
    // That same shared-nuxtApp behaviour means a component instance from an
    // *earlier* test (never explicitly unmounted - nothing in this file calls
    // wrapper.unmount()) can still be reactively wired to the 'admin-items'
    // cache and re-render when a *later* test's refresh()/submitItem() touches
    // it - and it re-renders using whatever `global.stubs` the later test
    // passed to mountSuspended(), not its own. Concretely: an earlier test
    // that left the create modal open with a real File selected can end up
    // rendering the real UFileUpload (because a later test stubs UModal open)
    // well after its own test has finished. UFileUpload renders an
    // object-URL thumbnail for each selected image file, and jsdom/Node's
    // URL.createObjectURL rejects File instances built by this file's
    // makeFile() helper as "not a Blob" across realms. Stub it globally so
    // that stray cross-test re-render is harmless either way - this is a test
    // environment shim, not a change to what's being asserted.
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ---- initial fetch / rendering ----

  it('fetches /items on mount and renders the item count and rows', async () => {
    callMock.mockResolvedValueOnce([makeItem({ name: 'Vintage Chair', price: 120 })])
    const wrapper = await mountSuspended(AdminItems)

    expect(callMock).toHaveBeenCalledWith('/items')
    expect(wrapper.text()).toContain('1 item(s)')
    expect(wrapper.text()).toContain('Vintage Chair')
    expect(wrapper.text()).toContain('RM 120.00')
  })

  it('falls back to the empty default state when the initial fetch rejects', async () => {
    callMock.mockRejectedValueOnce(new Error('network down'))
    const wrapper = await mountSuspended(AdminItems)

    expect(wrapper.text()).toContain('0 item(s)')
    expect((wrapper.vm as unknown as VmAny).items).toEqual([])
  })

  describe('firstImage', () => {
    it('returns undefined when image_path is null', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      expect(vm.firstImage(makeItem({ image_path: null }))).toBeUndefined()
    })

    it('returns the first URL from a valid JSON map', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      const item = makeItem({ image_path: JSON.stringify({ a: '/img/a.jpg', b: '/img/b.jpg' }) })
      expect(vm.firstImage(item)).toBe('/img/a.jpg')
    })

    it('returns undefined when image_path is not valid JSON', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      expect(vm.firstImage(makeItem({ image_path: 'not-json' }))).toBeUndefined()
    })
  })

  describe('formatDate', () => {
    it('formats an ISO date string using en-MY locale formatting', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      expect(vm.formatDate('2026-01-15T00:00:00Z')).toBe(
        new Date('2026-01-15T00:00:00Z').toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' })
      )
    })

    it('returns "-" for a falsy date', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      expect(vm.formatDate('')).toBe('-')
    })
  })

  // ---- openCreate / openEdit ----

  describe('openCreate / openEdit', () => {
    it('openCreate resets the form to defaults and opens the modal', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()

      expect(vm.open).toBe(true)
      expect(vm.editingId).toBeNull()
      expect(vm.isEditing).toBe(false)
      expect(vm.form.name).toBe('')
      expect(vm.form.description).toBe('')
      expect(vm.form.condition).toBe('Good')
      expect(vm.form.price).toBeUndefined()
      expect(vm.form.min_price).toBeUndefined()
      expect(vm.files).toEqual([])
    })

    it('openCreate clears out state left over from a previous openEdit', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openEdit(makeItem({ id: 'old-id', name: 'Old Name' }))
      expect(vm.editingId).toBe('old-id')

      vm.openCreate()

      expect(vm.editingId).toBeNull()
      expect(vm.isEditing).toBe(false)
      expect(vm.form.name).toBe('')
    })

    it('openEdit populates the form from the item and opens the modal', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      const item = makeItem({
        id: 'i2',
        name: 'Bookshelf',
        description: 'Solid oak',
        condition: 'Fair',
        price: 99,
        min_price: 20
      })

      vm.openEdit(item)

      expect(vm.open).toBe(true)
      expect(vm.editingId).toBe('i2')
      expect(vm.isEditing).toBe(true)
      expect(vm.form.name).toBe('Bookshelf')
      expect(vm.form.description).toBe('Solid oak')
      expect(vm.form.condition).toBe('Fair')
      expect(vm.form.price).toBe(99)
      expect(vm.form.min_price).toBe(20)
      expect(vm.files).toEqual([])
    })

    it('openEdit falls back to empty description, "Good" condition, and undefined min_price when missing', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      const item = makeItem({ description: '', condition: '', min_price: null })

      vm.openEdit(item)

      expect(vm.form.description).toBe('')
      expect(vm.form.condition).toBe('Good')
      expect(vm.form.min_price).toBeUndefined()
    })
  })

  // ---- canSubmit ----

  describe('canSubmit', () => {
    it('is false with no name, price, or files after openCreate', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      expect(vm.canSubmit).toBe(false)
    })

    it('is false with a name but no price', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = 'Chair'
      expect(vm.canSubmit).toBe(false)
    })

    it('is false with a whitespace-only name', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = '   '
      vm.form.price = 50
      expect(vm.canSubmit).toBe(false)
    })

    it('is false when creating with name + price but no files', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.files).toEqual([])
      expect(vm.canSubmit).toBe(false)
    })

    it('is true when creating with name + price + at least one file', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = 'Chair'
      vm.form.price = 50

      // Assigning `files` triggers the auto-analyze watcher as a side effect;
      // reject it so it resolves quickly via the fast catch branch instead of
      // idling on the component's internal timers.
      callMock.mockRejectedValueOnce(new Error('not used in this test'))
      vm.files = [makeFile()]

      expect(vm.canSubmit).toBe(true)
      await flushPromises()
    })

    it('is true when editing with name + price even without any files', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.files).toEqual([])
      expect(vm.canSubmit).toBe(true)
    })

    it('is false while isAnalyzing is true, even with a valid name/price', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      // Use edit mode so we don't have to touch `files` (and trigger the watcher).
      vm.openEdit(makeItem())
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.canSubmit).toBe(true)

      vm.isAnalyzing = true
      expect(vm.canSubmit).toBe(false)
    })
  })

  // ---- watch(files) auto-analyze ----

  describe('watch(files) auto-analyze', () => {
    it('does not call analyze-image while editing', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())

      vm.files = [makeFile()]
      await flushPromises()

      expect(callMock).toHaveBeenCalledTimes(1) // only the initial GET /items
      expect(vm.isAnalyzing).toBe(false)
    })

    it('does not call analyze-image again while an analysis is already in flight', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.isAnalyzing = true

      vm.files = [makeFile()]
      await flushPromises()

      expect(callMock).toHaveBeenCalledTimes(1) // only the initial GET /items
    })

    it('does not call analyze-image when the file list is empty', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      vm.files = [] // reference change, but still zero-length
      await flushPromises()

      expect(callMock).toHaveBeenCalledTimes(1)
    })

    it('posts a FormData of the selected files to /analyze-image', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      callMock.mockRejectedValueOnce(new Error('not used'))
      const file = makeFile('sofa.png')
      vm.files = [file]
      await flushPromises()

      const analyzeCall = callMock.mock.calls.find(([path]) => path === '/analyze-image')
      expect(analyzeCall).toBeTruthy()
      const [, opts] = analyzeCall!
      expect(opts.method).toBe('POST')
      expect(opts.body).toBeInstanceOf(FormData)
      expect((opts.body as FormData).getAll('images')).toEqual([file])
    })

    it('populates empty name/description/condition/price fields from a successful response and shows a success toast', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      vi.useFakeTimers()
      callMock.mockResolvedValueOnce({
        name: 'Leather Sofa',
        description: 'A comfy 3-seater',
        condition: 'like new',
        market_data: { suggested_listing: 899.99 }
      })

      vm.files = [makeFile('sofa.png')]
      await vi.advanceTimersByTimeAsync(1000)

      expect(vm.form.name).toBe('Leather Sofa')
      expect(vm.form.description).toBe('A comfy 3-seater')
      expect(vm.form.condition).toBe('Like New')
      expect(vm.form.price).toBe(899.99)
      expect(vm.isAnalyzing).toBe(false)
      expect(vm.progress).toBe(0)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Analysis complete',
        description: 'Item details have been auto-filled',
        color: 'success'
      })
    })

    it('does not overwrite name/description/price fields the user already filled in', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = 'My Own Name'
      vm.form.description = 'My own description'
      vm.form.price = 500

      vi.useFakeTimers()
      callMock.mockResolvedValueOnce({
        name: 'Detected Name',
        description: 'Detected description',
        market_data: { suggested_listing: 10 }
      })

      vm.files = [makeFile()]
      await vi.advanceTimersByTimeAsync(1000)

      expect(vm.form.name).toBe('My Own Name')
      expect(vm.form.description).toBe('My own description')
      expect(vm.form.price).toBe(500)
    })

    it('leaves condition unchanged when the response condition does not match any known key', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      expect(vm.form.condition).toBe('Good')

      vi.useFakeTimers()
      callMock.mockResolvedValueOnce({ condition: 'Mint' })

      vm.files = [makeFile()]
      await vi.advanceTimersByTimeAsync(1000)

      expect(vm.form.condition).toBe('Good')
    })

    it.each([
      ['new', 'New'],
      ['LIKE NEW', 'Like New'],
      ['good', 'Good'],
      ['Fair', 'Fair'],
      ['poor', 'Poor']
    ])('maps a response condition of "%s" to "%s" (case-insensitively)', async (input, expected) => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      vi.useFakeTimers()
      callMock.mockResolvedValueOnce({ condition: input })

      vm.files = [makeFile()]
      await vi.advanceTimersByTimeAsync(1000)

      expect(vm.form.condition).toBe(expected)
    })

    it('shows an "Analysis failed" toast with the API detail message when the request rejects', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      callMock.mockRejectedValueOnce({ data: { detail: 'Could not read image' } })
      vm.files = [makeFile()]
      await flushPromises()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Analysis failed',
        description: 'Could not read image',
        color: 'warning'
      })
      expect(vm.isAnalyzing).toBe(false)
      expect(vm.progress).toBe(0)
      expect(vm.form.name).toBe('')
    })

    it('falls back to err.message when the rejection has no API detail', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      callMock.mockRejectedValueOnce(new Error('boom'))
      vm.files = [makeFile()]
      await flushPromises()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Analysis failed',
        description: 'boom',
        color: 'warning'
      })
    })

    it('ticks progress upward via the interval on each 300ms tick while the analyze-image call is still pending', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()

      vi.useFakeTimers()
      let resolveCall!: (v: unknown) => void
      callMock.mockImplementationOnce(() => new Promise((resolve) => {
        resolveCall = resolve
      }))

      vm.files = [makeFile()]

      // Let the watcher's synchronous setup (isAnalyzing/progress reset, the
      // setInterval call) run before the analyze-image call resolves at all.
      await vi.advanceTimersByTimeAsync(0)
      expect(vm.isAnalyzing).toBe(true)
      expect(vm.progress).toBe(0)

      // First 300ms tick: progress.value (0) < 90, so it bumps up.
      await vi.advanceTimersByTimeAsync(300)
      const afterFirstTick = vm.progress
      expect(afterFirstTick).toBeGreaterThan(0)
      expect(afterFirstTick).toBeLessThan(90)

      // Second tick: still below 90, bumps up again - proves the interval
      // (not a one-shot timeout) is what's driving progress here.
      await vi.advanceTimersByTimeAsync(300)
      expect(vm.progress).toBeGreaterThan(afterFirstTick)
      expect(vm.progress).toBeLessThan(90)

      // Keep ticking (the increment shrinks toward 1/tick as progress
      // approaches 90) until it actually reaches the 90 ceiling, so the
      // `if (progress.value < 90)` guard's *false* branch - progress pinned
      // at 90, no further increments - gets exercised too, not just the
      // "still climbing" true branch above.
      await vi.advanceTimersByTimeAsync(300 * 40)
      expect(vm.progress).toBe(90)

      resolveCall({})
      await vi.advanceTimersByTimeAsync(1000)

      expect(vm.isAnalyzing).toBe(false)
      expect(vm.progress).toBe(0)
    })
  })

  // ---- submitItem ----

  describe('submitItem', () => {
    it('is a no-op when canSubmit is false', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate() // no name/price/files yet

      await vm.submitItem()

      expect(callMock).toHaveBeenCalledTimes(1) // only the initial GET /items
      expect(vm.saving).toBe(false)
    })

    describe('create (multipart FormData)', () => {
      async function setupCreatable(vm: VmAny) {
        vm.openCreate()
        vm.form.name = 'Guitar'
        vm.form.description = 'Six-string acoustic'
        vm.form.condition = 'Like New'
        vm.form.price = 250

        callMock.mockRejectedValueOnce(new Error('analyze not used'))
        vm.files = [makeFile('guitar.png')]
        await flushPromises() // let the (rejected) auto-analyze settle first
      }

      it('POSTs a FormData body to /items, toasts, closes the modal, and refreshes', async () => {
        callMock.mockResolvedValueOnce([])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny
        await setupCreatable(vm)

        callMock.mockResolvedValueOnce({ id: 'new-1' }) // POST /items
        callMock.mockResolvedValueOnce([makeItem({ id: 'new-1', name: 'Guitar' })]) // refresh()

        await vm.submitItem()

        const createCall = callMock.mock.calls.find(([path, opts]) => path === '/items' && opts?.method === 'POST')
        expect(createCall).toBeTruthy()
        const [, opts] = createCall!
        expect(opts.body).toBeInstanceOf(FormData)
        const body = opts.body as FormData
        expect(body.get('name')).toBe('Guitar')
        expect(body.get('description')).toBe('Six-string acoustic')
        expect(body.get('condition')).toBe('Like New')
        expect(body.get('price')).toBe('250')
        expect(body.get('min_price')).toBeNull()
        expect(body.getAll('images')).toHaveLength(1)

        expect(toastAddMock).toHaveBeenCalledWith({ title: 'Item created', color: 'success' })
        expect(vm.open).toBe(false)
        expect(vm.saving).toBe(false)
      })

      it('appends min_price to the FormData when provided', async () => {
        callMock.mockResolvedValueOnce([])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny
        await setupCreatable(vm)
        vm.form.min_price = 100

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([])

        await vm.submitItem()

        const createCall = callMock.mock.calls.find(([path, opts]) => path === '/items' && opts?.method === 'POST')
        const body = createCall![1].body as FormData
        expect(body.get('min_price')).toBe('100')
      })

      it('resets the form and clears editingId after a successful create', async () => {
        callMock.mockResolvedValueOnce([])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny
        await setupCreatable(vm)

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([])

        await vm.submitItem()

        expect(vm.form.name).toBe('')
        expect(vm.form.price).toBeUndefined()
        expect(vm.files).toEqual([])
        expect(vm.editingId).toBeNull()
      })

      it('shows a "Create failed" toast with the API detail and keeps the modal open on failure', async () => {
        callMock.mockResolvedValueOnce([])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny
        await setupCreatable(vm)

        callMock.mockRejectedValueOnce({ data: { detail: 'Server rejected the image' } })

        await vm.submitItem()

        expect(toastAddMock).toHaveBeenCalledWith({
          title: 'Create failed',
          description: 'Server rejected the image',
          color: 'error'
        })
        expect(vm.open).toBe(true)
        expect(vm.saving).toBe(false)
      })

      it('falls back to err.message on create failure when there is no API detail', async () => {
        callMock.mockResolvedValueOnce([])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny
        await setupCreatable(vm)

        callMock.mockRejectedValueOnce(new Error('upload timed out'))

        await vm.submitItem()

        expect(toastAddMock).toHaveBeenCalledWith({
          title: 'Create failed',
          description: 'upload timed out',
          color: 'error'
        })
      })
    })

    describe('edit (JSON PUT)', () => {
      it('PUTs a JSON body to /items/:id, toasts, closes the modal, and refreshes', async () => {
        const original = makeItem({ id: 'i5', name: 'Old Name', description: 'Old desc', condition: 'Fair', price: 40, min_price: 10 })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.name = 'New Name'
        vm.form.price = 75

        callMock.mockResolvedValueOnce({}) // PUT
        callMock.mockResolvedValueOnce([original]) // refresh()

        await vm.submitItem()

        expect(callMock).toHaveBeenCalledWith('/items/i5', {
          method: 'PUT',
          body: {
            name: 'New Name',
            description: 'Old desc',
            condition: 'Fair',
            price: 75,
            min_price: 10
          }
        })
        expect(toastAddMock).toHaveBeenCalledWith({ title: 'Item updated', color: 'success' })
        expect(vm.open).toBe(false)
        expect(vm.saving).toBe(false)
      })

      it('sends min_price: null when the minimum price field is left empty', async () => {
        const original = makeItem({ id: 'i6', min_price: 10 })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.min_price = undefined

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([original])

        await vm.submitItem()

        expect(callMock).toHaveBeenCalledWith('/items/i6', expect.objectContaining({
          method: 'PUT',
          body: expect.objectContaining({ min_price: null })
        }))
      })

      it('does not touch images/files on an edit submit', async () => {
        const original = makeItem({ id: 'i7' })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.price = 60

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([original])

        await vm.submitItem()

        const [, opts] = callMock.mock.calls.find(([path]) => path === '/items/i7')!
        expect(opts.body).not.toBeInstanceOf(FormData)
        expect(typeof opts.body).toBe('object')
      })

      it('shows an "Update failed" toast with the API detail and keeps the modal open on failure', async () => {
        const original = makeItem({ id: 'i8' })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.price = 60

        callMock.mockRejectedValueOnce({ data: { detail: 'Price below minimum' } })

        await vm.submitItem()

        expect(toastAddMock).toHaveBeenCalledWith({
          title: 'Update failed',
          description: 'Price below minimum',
          color: 'error'
        })
        expect(vm.open).toBe(true)
        expect(vm.saving).toBe(false)
      })

      it('falls back to err.message on update failure when there is no API detail', async () => {
        const original = makeItem({ id: 'i9' })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.price = 60

        callMock.mockRejectedValueOnce(new Error('server exploded'))

        await vm.submitItem()

        expect(toastAddMock).toHaveBeenCalledWith({
          title: 'Update failed',
          description: 'server exploded',
          color: 'error'
        })
      })
    })

    it('sets saving to true while the request is in flight, then false', async () => {
      const original = makeItem({ id: 'i10' })
      callMock.mockResolvedValueOnce([original])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(original)
      vm.form.price = 60

      let resolveCall!: (v: unknown) => void
      callMock.mockImplementationOnce(() => new Promise((resolve) => {
        resolveCall = resolve
      }))

      const pending = vm.submitItem()
      await Promise.resolve() // let submitItem() run up to its first await
      expect(vm.saving).toBe(true)

      resolveCall({})
      callMock.mockResolvedValueOnce([original]) // refresh()
      await pending

      expect(vm.saving).toBe(false)
    })
  })

  // ---- remove ----

  describe('remove', () => {
    it('DELETEs the item, shows a success toast, and refreshes the list', async () => {
      const item = makeItem({ id: 'i20' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      callMock.mockResolvedValueOnce({}) // DELETE
      callMock.mockResolvedValueOnce([]) // refresh()

      await vm.remove(item)

      expect(callMock).toHaveBeenCalledWith('/items/i20', { method: 'DELETE' })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Item deleted', color: 'success' })
      expect(callMock).toHaveBeenCalledTimes(3)
      expect(vm.busy).toBeNull()
    })

    it('sets busy to the item id while the delete is in flight, then clears it', async () => {
      const item = makeItem({ id: 'i21' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      let resolveCall!: (v: unknown) => void
      callMock.mockImplementationOnce(() => new Promise((resolve) => {
        resolveCall = resolve
      }))

      const pending = vm.remove(item)
      expect(vm.busy).toBe('i21')

      resolveCall({})
      callMock.mockResolvedValueOnce([]) // refresh()
      await pending

      expect(vm.busy).toBeNull()
    })

    it('shows a "Delete failed" toast with the API detail message on failure', async () => {
      const item = makeItem({ id: 'i22' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      callMock.mockRejectedValueOnce({ data: { detail: 'Item has a pending order' } })

      await vm.remove(item)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Delete failed',
        description: 'Item has a pending order',
        color: 'error'
      })
      expect(vm.busy).toBeNull()
    })

    it('falls back to err.message when the delete error has no API detail', async () => {
      const item = makeItem({ id: 'i23' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      callMock.mockRejectedValueOnce(new Error('server exploded'))

      await vm.remove(item)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Delete failed',
        description: 'server exploded',
        color: 'error'
      })
    })
  })

  // ---- template bindings: header/table buttons + the modal's v-model wiring ----
  // These don't need the UModal stub - the header buttons and per-row action
  // buttons live outside the modal entirely, and the modal's own root
  // component (as opposed to its teleported #body/#footer content) is still
  // reachable via findComponent even though its slot content never renders.

  describe('DOM interactions: header/row buttons and modal open v-model', () => {
    it('clicking the Refresh button in the header re-fetches the item list', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      callMock.mockResolvedValueOnce([makeItem({ name: 'Refreshed Item' })])
      const refreshBtn = wrapper.findAllComponents({ name: 'UButton' }).find(b => b.props('label') === 'Refresh')
      expect(refreshBtn).toBeTruthy()
      await refreshBtn!.trigger('click')
      await flushPromises()

      // Asserted at the useAsyncData/vm level rather than via rendered table
      // rows: <UTable>'s empty-state row (BUG, documented not fixed - see
      // rules) does not re-render into the populated rows once `items` goes
      // from an empty array to a populated one via useAsyncData's refresh() -
      // `vm.items` and `callMock` both update correctly (refresh() itself
      // works exactly as intended), but wrapper.text() keeps showing "No
      // data" for the table body. Reproduced directly against @nuxt/ui's
      // <UTable> outside of this component too, so it isn't something
      // `refresh()`/AdminItems.vue can influence.
      expect(callMock).toHaveBeenCalledTimes(2)
      expect(callMock).toHaveBeenNthCalledWith(2, '/items')
      expect(vm.items).toEqual([makeItem({ name: 'Refreshed Item' })])
    })

    it('clicking a row\'s edit (pencil) button opens the edit modal populated with that row', async () => {
      const item = makeItem({ id: 'row-1', name: 'Lamp' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      const editBtn = wrapper.findAllComponents({ name: 'UButton' }).find(b => b.props('icon') === 'i-lucide-pencil')
      expect(editBtn).toBeTruthy()
      await editBtn!.trigger('click')

      expect(vm.open).toBe(true)
      expect(vm.editingId).toBe('row-1')
      expect(vm.form.name).toBe('Lamp')
    })

    it('clicking a row\'s delete (trash) button removes that row', async () => {
      const item = makeItem({ id: 'row-2', name: 'Lamp' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)

      callMock.mockResolvedValueOnce({}) // DELETE
      callMock.mockResolvedValueOnce([]) // refresh()

      const deleteBtn = wrapper.findAllComponents({ name: 'UButton' }).find(b => b.props('icon') === 'i-lucide-trash-2')
      expect(deleteBtn).toBeTruthy()
      await deleteBtn!.trigger('click')
      await flushPromises()

      expect(callMock).toHaveBeenCalledWith('/items/row-2', { method: 'DELETE' })
    })

    it('emitting update:open(false) from the modal (Escape/overlay dismiss) closes it', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()
      expect(vm.open).toBe(true)

      const modal = wrapper.findComponent({ name: 'UModal' })
      expect(modal.exists()).toBe(true)
      modal.vm.$emit('update:open', false)
      await flushPromises()

      expect(vm.open).toBe(false)
    })
  })

  // ---- modal body/footer template (UModal stubbed so its slot content renders inline) ----

  describe('modal body/footer fields (via UModalStub)', () => {
    it('creating: shows the images upload field plus empty name/description/condition/price/min-price fields', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      expect(wrapper.find('input[type="file"]').exists()).toBe(true)

      const nameInput = wrapper.find('input[placeholder="e.g. Fender Stratocaster"]')
      expect(nameInput.exists()).toBe(true)
      expect((nameInput.element as HTMLInputElement).value).toBe('')

      const description = wrapper.find('textarea')
      expect(description.exists()).toBe(true)
      expect((description.element as HTMLTextAreaElement).value).toBe('')

      const conditionSelect = wrapper.findAll('button').find(b => b.attributes('role') === 'combobox')
      expect(conditionSelect).toBeTruthy()
      expect(conditionSelect!.text()).toContain('Good')

      const price = wrapper.find('input[placeholder="0.00"]')
      expect(price.exists()).toBe(true)
      expect((price.element as HTMLInputElement).value).toBe('')

      const minPrice = wrapper.find('input[placeholder="Optional"]')
      expect(minPrice.exists()).toBe(true)
      expect((minPrice.element as HTMLInputElement).value).toBe('')

      expect(wrapper.text()).not.toContain('Image editing isn\'t supported here')
    })

    it('editing: hides the images upload field, prefills fields from the item, and shows the edit-images hint', async () => {
      const item = makeItem({
        id: 'i60',
        name: 'Bookshelf',
        description: 'Solid oak',
        condition: 'Fair',
        price: 99,
        min_price: 20
      })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(item)
      await flushPromises()

      expect(wrapper.find('input[type="file"]').exists()).toBe(false)

      const nameInput = wrapper.find('input[placeholder="e.g. Fender Stratocaster"]')
      expect((nameInput.element as HTMLInputElement).value).toBe('Bookshelf')

      const description = wrapper.find('textarea')
      expect((description.element as HTMLTextAreaElement).value).toBe('Solid oak')

      const conditionSelect = wrapper.findAll('button').find(b => b.attributes('role') === 'combobox')
      expect(conditionSelect!.text()).toContain('Fair')

      const price = wrapper.find('input[placeholder="0.00"]')
      expect((price.element as HTMLInputElement).value).toBe('99')

      const minPrice = wrapper.find('input[placeholder="Optional"]')
      expect((minPrice.element as HTMLInputElement).value).toBe('20')

      expect(wrapper.text()).toContain('Image editing isn\'t supported here — existing images are kept.')
    })

    it('typing into the Name/Description/Price/Minimum price fields updates the form via v-model', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      await wrapper.find('input[placeholder="e.g. Fender Stratocaster"]').setValue('Standing Desk')
      await wrapper.find('textarea').setValue('Adjustable height')
      await wrapper.find('input[placeholder="0.00"]').setValue('150')
      await wrapper.find('input[placeholder="Optional"]').setValue('75')

      expect(vm.form.name).toBe('Standing Desk')
      expect(vm.form.description).toBe('Adjustable height')
      expect(vm.form.price).toBe(150)
      expect(vm.form.min_price).toBe(75)
    })

    it('changing the Condition select and the Images upload updates the form via v-model', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      // Reka UI's <USelect> opens its option list in a teleported popover,
      // which - like <UModal>'s own body/footer - never renders into this
      // harness's detached wrapper tree, so it can't be driven via a real
      // click-to-select. Emitting the same "update:modelValue" event its
      // internal listbox would emit on selection exercises the exact same
      // v-model setter on AdminItems' side.
      const select = wrapper.findComponent({ name: 'USelect' })
      expect(select.exists()).toBe(true)
      select.vm.$emit('update:modelValue', 'Fair')
      await flushPromises()
      expect(vm.form.condition).toBe('Fair')

      const fileUpload = wrapper.findComponent({ name: 'UFileUpload' })
      expect(fileUpload.exists()).toBe(true)
      const file = makeFile('desk.png')
      fileUpload.vm.$emit('update:modelValue', [file])
      await flushPromises()
      expect(vm.files).toEqual([file])
    })

    it('clicking Cancel in the footer closes the modal without submitting anything', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      const cancelBtn = wrapper.findAll('button').find(b => b.text() === 'Cancel')
      expect(cancelBtn).toBeTruthy()
      await cancelBtn!.trigger('click')

      expect(vm.open).toBe(false)
      expect(callMock).toHaveBeenCalledTimes(1) // only the initial GET /items
    })

    it('clicking "Create item" in the footer submits the new item', async () => {
      callMock.mockResolvedValueOnce([])
      // This test isn't about the images field itself (covered separately
      // above), so stub UFileUpload out too - AdminItems.vue's own
      // <UFileUpload v-model="files" /> binding still gets exercised (that
      // vnode is still created), just without mounting the real child.
      const wrapper = await mountSuspended(AdminItems, {
        global: { stubs: { UModal: UModalStub, UFileUpload: true } }
      })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = 'Guitar'
      vm.form.price = 250

      callMock.mockRejectedValueOnce(new Error('analyze not used'))
      vm.files = [makeFile('guitar.png')]
      await flushPromises()

      callMock.mockResolvedValueOnce({ id: 'new-1' }) // POST /items
      callMock.mockResolvedValueOnce([]) // refresh()

      const submitBtn = wrapper.findAll('button').find(b => b.text() === 'Create item')
      expect(submitBtn).toBeTruthy()
      expect(submitBtn!.attributes('disabled')).toBeUndefined()
      await submitBtn!.trigger('click')
      await flushPromises()

      const createCall = callMock.mock.calls.find(([path, opts]) => path === '/items' && opts?.method === 'POST')
      expect(createCall).toBeTruthy()
      expect(vm.open).toBe(false)
    })

    it('clicking "Save changes" in the footer submits the edit', async () => {
      const original = makeItem({ id: 'i70', name: 'Old Name', price: 40 })
      callMock.mockResolvedValueOnce([original])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(original)
      await flushPromises()

      callMock.mockResolvedValueOnce({}) // PUT
      callMock.mockResolvedValueOnce([original]) // refresh()

      const submitBtn = wrapper.findAll('button').find(b => b.text() === 'Save changes')
      expect(submitBtn).toBeTruthy()
      expect(submitBtn!.attributes('disabled')).toBeUndefined()
      await submitBtn!.trigger('click')
      await flushPromises()

      expect(callMock).toHaveBeenCalledWith('/items/i70', expect.objectContaining({ method: 'PUT' }))
      expect(vm.open).toBe(false)
    })
  })
})
