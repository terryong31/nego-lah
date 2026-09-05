import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import AdminItems from '~/components/admin/AdminItems.vue'

const { callMock, toastAddMock, analyzeMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn(),
  analyzeMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

// The streaming analysis itself is covered by tests/composables/useItemAnalysis.test.ts;
// here we only care that the component drives it and applies what comes back.
// Fresh refs per instance mirror the real composable, and the component
// re-exposes them, so tests can still read/write vm.isAnalyzing & vm.progress.
mockNuxtImport('useItemAnalysis', () => () => ({
  analyze: analyzeMock,
  isAnalyzing: ref(false),
  progress: ref(0),
  stageMessage: ref('')
}))

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

// The stored photo map on a listing: {storage filename: public url}, whose
// insertion order is the display order (first = thumbnail).
const STORED = { '0.jpg': 'https://cdn.test/a.jpg', '1.jpg': 'https://cdn.test/b.jpg' }

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: 'item-1',
    name: 'Vintage Chair',
    description: 'A comfy chair',
    condition: 'Good',
    price: 120,
    min_price: null,
    image_path: JSON.stringify(STORED),
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
  template: '<div><slot v-if="open" name="title" /><slot v-if="open" name="body" /><slot v-if="open" name="footer" /></div>'
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
    translations: Record<string, { name: string, description: string, condition: string }>
  }
  activeLang: 'en' | 'ms' | 'zh'
  currentName: string
  currentDescription: string
  files: File[]
  images: StagedImage[]
  step: 'choose' | 'photos' | 'details'
  mode: 'manual' | 'ai'
  autofilled: boolean
  dragIndex: number | null
  isAnalyzing: boolean
  progress: number
  busy: string | null
  canSubmit: boolean
  openCreate: () => void
  openEdit: (item: Item) => void
  startManual: () => void
  startAi: () => void
  detectAndContinue: () => Promise<void>
  skipToManual: () => void
  goBack: () => void
  moveImage: (from: number, to: number) => void
  removeImage: (index: number) => void
  dropOn: (index: number) => void
  addImages: (files: File[]) => void
  submitItem: () => Promise<void>
  remove: (item: Item) => Promise<void>
  firstImage: (item: Item) => string | undefined
  formatDate: (d: string) => string
}

/** A photo staged in the grid: either newly picked, or already on the listing. */
type StagedImage
  = | { id: string, kind: 'new', file: File, url: string }
    | { id: string, kind: 'existing', url: string }

/** Identify each staged photo: a new one by filename, a stored one by its URL. */
function names(vm: VmAny) {
  return vm.images.map(i => (i.kind === 'new' ? i.file.name : i.url))
}

/** Open the create modal on the manual path with the named photos staged. */
function stageManual(vm: VmAny, ...names: string[]) {
  vm.openCreate()
  vm.startManual()
  vm.addImages(names.map(n => makeFile(n)))
}

describe('components/admin/AdminItems.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    analyzeMock.mockReset()
    analyzeMock.mockResolvedValue({})
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
      expect(vm.images).toEqual([])
      expect(vm.step).toBe('choose')
      expect(vm.autofilled).toBe(false)
    })

    it('openCreate returns to the choice screen after a previous create reached the details step', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      stageManual(vm, 'a.png')
      expect(vm.step).toBe('details')

      vm.open = false
      await flushPromises()
      vm.openCreate()

      expect(vm.step).toBe('choose')
      expect(vm.images).toEqual([])
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

    it('openEdit seeds the photo grid from image_path, in stored order', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openEdit(makeItem({ id: 'i2' }))

      expect(vm.images.map(i => i.kind)).toEqual(['existing', 'existing'])
      expect(vm.images.map(i => i.url)).toEqual(['https://cdn.test/a.jpg', 'https://cdn.test/b.jpg'])
    })

    it('openEdit leaves the grid empty for an item with no usable image_path', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openEdit(makeItem({ image_path: null }))
      expect(vm.images).toEqual([])

      vm.openEdit(makeItem({ image_path: 'not-json' }))
      expect(vm.images).toEqual([])
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

    it('is false when creating with name + price but no photos staged', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.images).toEqual([])
      expect(vm.canSubmit).toBe(false)
    })

    it('is true when creating with name + price + at least one staged photo', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'chair.png')
      vm.form.name = 'Chair'
      vm.form.price = 50

      expect(vm.canSubmit).toBe(true)
    })

    it('is true when editing with name + price and the item\'s stored photos', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.images).toHaveLength(2)
      expect(vm.canSubmit).toBe(true)
    })

    it('is false when editing after every photo has been removed', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.form.name = 'Chair'
      vm.form.price = 50

      vm.removeImage(0)
      vm.removeImage(0)

      expect(vm.images).toEqual([])
      expect(vm.canSubmit).toBe(false)
    })

    it('is false while isAnalyzing is true, even with a valid name/price', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.canSubmit).toBe(true)

      vm.isAnalyzing = true
      expect(vm.canSubmit).toBe(false)
    })
  })

  // ---- choosing a create mode ----

  describe('create mode choice', () => {
    it('openCreate lands on the choice screen with no mode committed', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()

      expect(vm.step).toBe('choose')
      expect(vm.canSubmit).toBe(false)
    })

    it('startManual goes straight to the details step', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()
      vm.startManual()

      expect(vm.mode).toBe('manual')
      expect(vm.step).toBe('details')
      expect(analyzeMock).not.toHaveBeenCalled()
    })

    it('startAi goes to the photos step without analyzing anything yet', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()
      vm.startAi()

      expect(vm.mode).toBe('ai')
      expect(vm.step).toBe('photos')
      expect(analyzeMock).not.toHaveBeenCalled()
    })

    it('goBack returns from manual details to the choice screen', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      stageManual(vm, 'a.png')
      vm.goBack()

      expect(vm.step).toBe('choose')
    })

    it('goBack returns from AI details to the photos step, restoring the picker selection', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      const file = makeFile('lamp.png')

      vm.openCreate()
      vm.startAi()
      vm.files = [file]
      await vm.detectAndContinue()
      expect(vm.step).toBe('details')

      vm.goBack()

      expect(vm.step).toBe('photos')
      expect(vm.files).toEqual([file])
    })

    it('goBack from the photos step returns to the choice screen', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()
      vm.startAi()
      vm.goBack()

      expect(vm.step).toBe('choose')
    })
  })

  // ---- AI detect step ----

  describe('detectAndContinue', () => {
    it('does nothing without any selected photos', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()

      await vm.detectAndContinue()

      expect(analyzeMock).not.toHaveBeenCalled()
      expect(vm.step).toBe('photos')
    })

    it('does not start a second analysis while one is already in flight', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]
      vm.isAnalyzing = true

      await vm.detectAndContinue()

      expect(analyzeMock).not.toHaveBeenCalled()
    })

    it('hands the selected photos to the analyzer and stages them in picked order', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      const first = makeFile('front.png')
      const second = makeFile('back.png')
      vm.files = [first, second]

      await vm.detectAndContinue()

      expect(analyzeMock).toHaveBeenCalledTimes(1)
      expect(analyzeMock.mock.calls[0]![0]).toEqual([first, second])
      expect(vm.images.map(i => i.file)).toEqual([first, second])
      expect(vm.step).toBe('details')
    })

    it('populates empty name/description/condition/price fields and flags the form as auto-filled', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile('sofa.png')]

      analyzeMock.mockResolvedValueOnce({
        name: 'Leather Sofa',
        description: 'A comfy 3-seater',
        condition: 'like new',
        market_data: { suggested_listing: 899.99 }
      })

      await vm.detectAndContinue()

      expect(vm.form.name).toBe('Leather Sofa')
      expect(vm.form.description).toBe('A comfy 3-seater')
      expect(vm.form.condition).toBe('Like New')
      expect(vm.form.price).toBe(899.99)
      expect(vm.autofilled).toBe(true)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Analysis complete',
        description: 'Item details have been auto-filled',
        color: 'success'
      })
    })

    it('populates trilingual translations when provided by AI analysis', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile('keyboard.png')]

      analyzeMock.mockResolvedValueOnce({
        name: 'Mechanical Keyboard',
        description: 'RGB wireless mechanical keyboard',
        condition: 'good',
        translations: {
          en: { name: 'Mechanical Keyboard', description: 'RGB wireless keyboard', condition: 'Good' },
          ms: { name: 'Papan Kekunci Mekanikal', description: 'Papan kekunci tanpa wayar RGB', condition: 'Baik' },
          zh: { name: '机械键盘', description: 'RGB无线机械键盘', condition: '良好' }
        }
      })

      await vm.detectAndContinue()

      expect(vm.form.translations.en.name).toBe('Mechanical Keyboard')
      expect(vm.form.translations.ms.name).toBe('Papan Kekunci Mekanikal')
      expect(vm.form.translations.zh.name).toBe('机械键盘')
      expect(vm.form.translations.ms.description).toBe('Papan kekunci tanpa wayar RGB')
    })

    it('defensively extracts trilingual fields when description contains serialized JSON without translations object', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile('headphones.png')]

      const rawJson = `\`\`\`json
{
  "en": {
    "name": "AirPods Max Space Gray",
    "description": "Premium wireless headphones with Active Noise Cancellation.",
    "condition": "Like New"
  },
  "ms": {
    "name": "AirPods Max Kelabu",
    "description": "Fon kepala tanpa wayar premium dengan Pembatalan Hingar Aktif.",
    "condition": "Seperti Baru"
  },
  "zh": {
    "name": "AirPods Max 深空灰",
    "description": "具备主动降噪功能的高端无线耳机。",
    "condition": "几乎全新"
  }
}
\`\`\``

      analyzeMock.mockResolvedValueOnce({
        name: 'AirPods Max Space Gray',
        description: rawJson,
        condition: 'like new',
        market_data: { suggested_listing: 1250 }
      })

      await vm.detectAndContinue()

      expect(vm.form.description).toBe('Premium wireless headphones with Active Noise Cancellation.')
      expect(vm.form.description).not.toContain('```json')
      expect(vm.form.translations.en.description).toBe('Premium wireless headphones with Active Noise Cancellation.')
      expect(vm.form.translations.ms.name).toBe('AirPods Max Kelabu')
      expect(vm.form.translations.ms.description).toBe('Fon kepala tanpa wayar premium dengan Pembatalan Hingar Aktif.')
      expect(vm.form.translations.zh.name).toBe('AirPods Max 深空灰')
      expect(vm.form.translations.zh.description).toBe('具备主动降噪功能的高端无线耳机。')
    })

    it('applies streamed patches as they arrive, before the analysis finishes', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile('lamp.png')]

      // Stand in for the SSE stages landing one at a time.
      analyzeMock.mockImplementationOnce(async (_files, onPatch) => {
        onPatch({ name: 'Brass Lamp', condition: 'good' })
        expect(vm.form.name).toBe('Brass Lamp')
        onPatch({ description: 'Warm glow', price: 120 })
        return { name: 'Brass Lamp' }
      })

      await vm.detectAndContinue()

      expect(vm.form.name).toBe('Brass Lamp')
      expect(vm.form.description).toBe('Warm glow')
      expect(vm.form.price).toBe(120)
    })

    it('does not overwrite name/description/price fields the user already filled in', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]
      vm.form.name = 'My Own Name'
      vm.form.description = 'My own description'
      vm.form.price = 500

      analyzeMock.mockResolvedValueOnce({
        name: 'Detected Name',
        description: 'Detected description',
        market_data: { suggested_listing: 10 }
      })

      await vm.detectAndContinue()

      expect(vm.form.name).toBe('My Own Name')
      expect(vm.form.description).toBe('My own description')
      expect(vm.form.price).toBe(500)
    })

    it('leaves condition unchanged when the response condition does not match any known key', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]
      expect(vm.form.condition).toBe('Good')

      analyzeMock.mockResolvedValueOnce({ condition: 'Mint' })

      await vm.detectAndContinue()

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
      vm.startAi()
      vm.files = [makeFile()]

      analyzeMock.mockResolvedValueOnce({ condition: input })

      await vm.detectAndContinue()

      expect(vm.form.condition).toBe(expected)
    })

    it('warns but still advances to the details step when the analysis fails', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]

      analyzeMock.mockRejectedValueOnce({ data: { detail: 'Could not read image' } })

      await vm.detectAndContinue()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Analysis failed',
        description: 'Could not read image',
        color: 'warning'
      })
      // Still usable: the photos are staged and the form is just blank.
      expect(vm.step).toBe('details')
      expect(vm.images).toHaveLength(1)
      expect(vm.autofilled).toBe(false)
      expect(vm.form.name).toBe('')
    })

    it('falls back to err.message when the rejection has no API detail', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]

      analyzeMock.mockRejectedValueOnce(new Error('boom'))

      await vm.detectAndContinue()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Analysis failed',
        description: 'boom',
        color: 'warning'
      })
    })

    it('skipToManual stages the picked photos without analyzing them', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      const file = makeFile('desk.png')
      vm.files = [file]

      vm.skipToManual()

      expect(analyzeMock).not.toHaveBeenCalled()
      expect(vm.mode).toBe('manual')
      expect(vm.step).toBe('details')
      expect(vm.images.map(i => i.file)).toEqual([file])
    })
  })

  // ---- photo ordering ----

  describe('photo ordering', () => {
    it('addImages appends to the end, keeping the existing thumbnail first', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')

      vm.addImages([makeFile('c.png')])

      expect(names(vm)).toEqual(['a.png', 'b.png', 'c.png'])
    })

    it('moveImage reorders and can promote a later photo to the thumbnail slot', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png', 'c.png')

      vm.moveImage(2, 0)

      expect(names(vm)).toEqual(['c.png', 'a.png', 'b.png'])
    })

    it('moveImage ignores out-of-range targets', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')

      vm.moveImage(0, -1)
      vm.moveImage(1, 2)

      expect(names(vm)).toEqual(['a.png', 'b.png'])
    })

    it('removeImage drops the photo and revokes its preview URL', async () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')

      vm.removeImage(0)

      expect(names(vm)).toEqual(['b.png'])
      expect(revoke).toHaveBeenCalledWith('blob:mock-url')
      revoke.mockRestore()
    })

    it('removeImage never revokes a stored photo\'s URL', async () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())

      vm.removeImage(0)

      expect(names(vm)).toEqual(['https://cdn.test/b.jpg'])
      expect(revoke).not.toHaveBeenCalled()
      revoke.mockRestore()
    })

    it('closing the modal revokes staged previews but leaves stored URLs alone', async () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.addImages([makeFile('extra.png')])
      // Let the `open` watcher settle on true, so closing is a real transition
      // rather than a change Vue batches away.
      await flushPromises()

      vm.open = false
      await flushPromises()

      expect(revoke).toHaveBeenCalledTimes(1)
      expect(revoke).toHaveBeenCalledWith('blob:mock-url')
      expect(vm.images).toEqual([])
      revoke.mockRestore()
    })

    it('a stored photo can be reordered against a newly added one', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.addImages([makeFile('fresh.png')])

      vm.moveImage(2, 0)

      expect(names(vm)).toEqual(['fresh.png', 'https://cdn.test/a.jpg', 'https://cdn.test/b.jpg'])
    })

    it('removeImage is a no-op for an index that does not exist', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png')

      vm.removeImage(5)

      expect(names(vm)).toEqual(['a.png'])
    })

    it('dropOn moves the dragged photo onto the drop target', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png', 'c.png')

      vm.dragIndex = 0
      vm.dropOn(2)

      expect(names(vm)).toEqual(['b.png', 'c.png', 'a.png'])
      expect(vm.dragIndex).toBeNull()
    })

    it('dropOn does nothing without an active drag, or when dropped on itself', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')

      vm.dropOn(1)
      expect(names(vm)).toEqual(['a.png', 'b.png'])

      vm.dragIndex = 1
      vm.dropOn(1)
      expect(names(vm)).toEqual(['a.png', 'b.png'])
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
        stageManual(vm, 'guitar.png')
        vm.form.name = 'Guitar'
        vm.form.description = 'Six-string acoustic'
        vm.form.condition = 'Like New'
        vm.form.price = 250
        await flushPromises()
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
        expect(vm.images).toEqual([])
        expect(vm.step).toBe('choose')
        expect(vm.editingId).toBeNull()
      })

      it('appends the photos in the order they were arranged, thumbnail first', async () => {
        callMock.mockResolvedValueOnce([])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny
        stageManual(vm, 'a.png', 'b.png', 'c.png')
        vm.form.name = 'Guitar'
        vm.form.price = 250

        // Promote the last photo to the thumbnail slot.
        vm.moveImage(2, 0)

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([])

        await vm.submitItem()

        const createCall = callMock.mock.calls.find(([path, opts]) => path === '/items' && opts?.method === 'POST')
        const body = createCall![1].body as FormData
        expect((body.getAll('images') as File[]).map(f => f.name)).toEqual(['c.png', 'a.png', 'b.png'])
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

    describe('edit (multipart FormData)', () => {
      /** The FormData the component PUT to /items/:id. */
      function editBody(path: string): FormData {
        const call = callMock.mock.calls.find(([p, opts]) => p === path && opts?.method === 'PUT')
        expect(call).toBeTruthy()
        expect(call![1].body).toBeInstanceOf(FormData)
        return call![1].body as FormData
      }

      it('PUTs a FormData body to /items/:id, toasts, closes the modal, and refreshes', async () => {
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

        const body = editBody('/items/i5')
        expect(body.get('name')).toBe('New Name')
        expect(body.get('description')).toBe('Old desc')
        expect(body.get('condition')).toBe('Fair')
        expect(body.get('price')).toBe('75')
        expect(body.get('min_price')).toBe('10')
        expect(JSON.parse(body.get('translations') as string)).toEqual({
          en: { name: 'New Name', description: 'Old desc', condition: 'Fair' },
          ms: { name: '', description: '', condition: '' },
          zh: { name: '', description: '', condition: '' }
        })

        expect(toastAddMock).toHaveBeenCalledWith({ title: 'Item updated', color: 'success' })
        expect(vm.open).toBe(false)
        expect(vm.saving).toBe(false)
      })

      it('sends an empty min_price when the minimum price field is left empty', async () => {
        const original = makeItem({ id: 'i6', min_price: 10 })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.min_price = undefined

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([original])

        await vm.submitItem()

        expect(editBody('/items/i6').get('min_price')).toBeNull()
      })

      it('keeps every stored photo, in order, when the grid is untouched', async () => {
        const original = makeItem({ id: 'i7' })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.price = 60

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([original])

        await vm.submitItem()

        const body = editBody('/items/i7')
        expect(JSON.parse(body.get('images_order') as string)).toEqual([
          'https://cdn.test/a.jpg',
          'https://cdn.test/b.jpg'
        ])
        expect(body.getAll('new_images')).toHaveLength(0)
      })

      it('interleaves kept URLs and new:<n> tokens to match the arranged order', async () => {
        const original = makeItem({ id: 'i11' })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.addImages([makeFile('fresh.png'), makeFile('newer.png')])
        // Arrange as: fresh, a.jpg, newer, b.jpg
        vm.moveImage(2, 0)
        vm.moveImage(3, 2)

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([original])

        await vm.submitItem()

        const body = editBody('/items/i11')
        expect(JSON.parse(body.get('images_order') as string)).toEqual([
          'new:0',
          'https://cdn.test/a.jpg',
          'new:1',
          'https://cdn.test/b.jpg'
        ])
        // The files are appended in token order, so new:0 is the first of them.
        expect((body.getAll('new_images') as File[]).map(f => f.name)).toEqual(['fresh.png', 'newer.png'])
      })

      it('drops removed photos from images_order so the backend deletes them', async () => {
        const original = makeItem({ id: 'i12' })
        callMock.mockResolvedValueOnce([original])
        const wrapper = await mountSuspended(AdminItems)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.removeImage(0)

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([original])

        await vm.submitItem()

        expect(JSON.parse(editBody('/items/i12').get('images_order') as string)).toEqual([
          'https://cdn.test/b.jpg'
        ])
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

    it('renders empty state with an action button that opens the create modal', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems)
      const vm = wrapper.vm as unknown as VmAny
      await flushPromises()

      const empty = wrapper.findComponent({ name: 'UEmpty' })
      expect(empty.exists()).toBe(true)
      expect(empty.props('title')).toBe('No items found')

      const uploadBtn = empty.findComponent({ name: 'UButton' })
      expect(uploadBtn.exists()).toBe(true)
      expect(uploadBtn.props('label')).toBe('Upload item')

      await uploadBtn.trigger('click')
      await flushPromises()
      expect(vm.open).toBe(true)
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
    it('creating: offers the manual and AI paths before showing any fields', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      expect(wrapper.text()).toContain('Fill in manually')
      expect(wrapper.text()).toContain('Let AI detect it')
      // Nothing to fill in or upload yet.
      expect(wrapper.find('input[placeholder="e.g. Fender Stratocaster"]').exists()).toBe(false)
      expect(wrapper.findComponent({ name: 'UFileUpload' }).exists()).toBe(false)
    })

    it('creating: clicking "Let AI detect it" opens the photo picker', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      const aiChoice = wrapper.findAll('button').find(b => b.text().includes('Let AI detect it'))
      expect(aiChoice).toBeTruthy()
      await aiChoice!.trigger('click')
      await flushPromises()

      expect(vm.step).toBe('photos')
      expect(wrapper.findComponent({ name: 'UFileUpload' }).exists()).toBe(true)
    })

    it('creating: clicking "Fill in manually" shows the empty name/description/condition/price/min-price fields', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      const manualChoice = wrapper.findAll('button').find(b => b.text().includes('Fill in manually'))
      expect(manualChoice).toBeTruthy()
      await manualChoice!.trigger('click')
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

    it('editing: shows the photo grid alongside the prefilled fields', async () => {
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

      const tiles = wrapper.findAll('[data-testid="image-tile"]')
      expect(tiles).toHaveLength(2)
      expect(tiles[0]!.text()).toContain('Thumbnail')
      expect(tiles[0]!.find('img').attributes('src')).toBe('https://cdn.test/a.jpg')
      // The hidden "Add" picker is mounted, so photos can be added here too.
      expect(wrapper.find('input[type="file"]').exists()).toBe(true)

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

      expect(wrapper.text()).not.toContain('Image editing isn\'t supported here')
    })

    it('editing: clicking a tile\'s remove button drops that stored photo', async () => {
      const item = makeItem({ id: 'i61' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(item)
      await flushPromises()

      const remove = wrapper.findAll('button').find(b => b.attributes('aria-label') === 'Remove photo')
      await remove!.trigger('click')

      expect(names(vm)).toEqual(['https://cdn.test/b.jpg'])
      expect(wrapper.findAll('[data-testid="image-tile"]')).toHaveLength(1)
    })

    it('editing: Save changes is disabled once the last photo is removed', async () => {
      const item = makeItem({ id: 'i62' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(item)
      vm.removeImage(0)
      vm.removeImage(0)
      await flushPromises()

      const submitBtn = wrapper.findAll('button').find(b => b.text() === 'Save changes')
      expect(submitBtn!.attributes('disabled')).toBeDefined()
    })

    it('typing into the Name/Description/Price/Minimum price fields updates the form via v-model', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()
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

    it('switches language tabs and independently updates currentName and currentDescription', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()

      // Default active language is 'en'
      expect(vm.activeLang).toBe('en')
      vm.currentName = 'English Title'
      vm.currentDescription = 'English Desc'
      expect(vm.form.name).toBe('English Title')
      expect(vm.form.translations.en.name).toBe('English Title')

      // Switch to 'ms'
      vm.activeLang = 'ms'
      expect(vm.currentName).toBe('')
      vm.currentName = 'Tajuk BM'
      vm.currentDescription = 'Deskripsi BM'
      expect(vm.form.translations.ms.name).toBe('Tajuk BM')
      expect(vm.form.name).toBe('English Title') // English untouched

      // Switch to 'zh'
      vm.activeLang = 'zh'
      expect(vm.currentName).toBe('')
      vm.currentName = '中文标题'
      vm.currentDescription = '中文描述'
      expect(vm.form.translations.zh.name).toBe('中文标题')
      expect(vm.form.translations.zh.description).toBe('中文描述')

      // Switch back to 'en'
      vm.activeLang = 'en'
      expect(vm.currentName).toBe('English Title')
    })

    it('renders listing language tabs using UTabs with variant="link"', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()
      await flushPromises()

      const tabs = wrapper.findComponent({ name: 'UTabs' })
      expect(tabs.exists()).toBe(true)
      expect(tabs.props('variant')).toBe('link')
      expect(tabs.props('items')).toEqual(expect.arrayContaining([
        expect.objectContaining({ label: 'English', value: 'en' }),
        expect.objectContaining({ label: 'Bahasa Melayu', value: 'ms' }),
        expect.objectContaining({ label: '简体中文', value: 'zh' })
      ]))
    })

    it('changing the Condition select updates the form via v-model', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()
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
    })

    it('the AI step\'s Images upload updates `files` via v-model', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      await flushPromises()

      const fileUpload = wrapper.findComponent({ name: 'UFileUpload' })
      expect(fileUpload.exists()).toBe(true)
      const file = makeFile('desk.png')
      fileUpload.vm.$emit('update:modelValue', [file])
      await flushPromises()
      expect(vm.files).toEqual([file])
    })

    it('the details step renders a tile per photo, badging the first as the thumbnail', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')
      await flushPromises()

      const tiles = wrapper.findAll('[data-testid="image-tile"]')
      expect(tiles).toHaveLength(2)
      expect(tiles[0]!.text()).toContain('Thumbnail')
      expect(tiles[1]!.text()).toContain('2')
    })

    it('dragging and dropping a tile reorders photos and updates the thumbnail', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')
      await flushPromises()

      vm.dragIndex = 1
      vm.dropOn(0)

      expect(names(vm)).toEqual(['b.png', 'a.png'])
    })

    it('clicking a tile\'s remove button drops that photo', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')
      await flushPromises()

      const remove = wrapper.findAll('button').find(b => b.attributes('aria-label') === 'Remove photo')
      expect(remove).toBeTruthy()
      await remove!.trigger('click')

      expect(names(vm)).toEqual(['b.png'])
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

    it('clicking the back button returns to the choice screen', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()
      await flushPromises()

      const backBtn = wrapper.findAll('button').find(b => b.attributes('aria-label') === 'Back')
      expect(backBtn).toBeTruthy()
      await backBtn!.trigger('click')

      expect(vm.step).toBe('choose')
    })

    it('uploading photos in the photos step immediately triggers AI detection', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      await flushPromises()

      expect(vm.step).toBe('photos')
      const photo = makeFile('chair.png')
      vm.onPhotosUploaded([photo])
      await flushPromises()

      expect(vm.step).toBe('details')
      expect(vm.images.length).toBe(1)
    })

    it('clicking "Create item" in the footer submits the new item', async () => {
      callMock.mockResolvedValueOnce([])
      const wrapper = await mountSuspended(AdminItems, {
        global: { stubs: { UModal: UModalStub } }
      })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'guitar.png')
      vm.form.name = 'Guitar'
      vm.form.price = 250
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
