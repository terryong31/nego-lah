import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import AdminItemFormModal from '~/components/admin/AdminItemFormModal.vue'
import { makePendingImage } from '~/composables/useItemImages'

// The create/edit form, split out of AdminItems.vue (SPEC-037). Everything to
// do with form state, the AI draft step, photo staging and submission lives
// here; the list component's own tests are in AdminItems.test.ts.
//
// The component owns its `open` state and is driven through the two methods it
// exposes to its parent, `openCreate()` / `openEdit(item)`. It no longer
// refreshes the list itself — it emits `saved`, which is what these tests
// assert in place of the old refresh() call.

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
}

/** A photo staged in the grid: either newly picked, or already on the listing. */
type StagedImage
  = | { id: string, kind: 'new', file: File, url: string }
    | { id: string, kind: 'existing', url: string }

/** Identify each staged photo: a new one by filename, a stored one by its URL. */
function names(vm: VmAny) {
  return vm.images.map(i => (i.kind === 'new' ? i.file.name : i.url))
}

/** Stage the named photos on the grid, in order. */
function stage(vm: VmAny, ...names: string[]) {
  vm.images = names.map(n => makePendingImage(makeFile(n)))
}

/** Append photos to whatever is already staged. */
function append(vm: VmAny, ...names: string[]) {
  vm.images = [...vm.images, ...names.map(n => makePendingImage(makeFile(n)))]
}

/** Rearrange the staged photos into the given order, by filename or URL. */
function arrange(vm: VmAny, ...order: string[]) {
  const byName = new Map(vm.images.map(i => [i.kind === 'new' ? i.file.name : i.url, i]))
  vm.images = order.map(n => byName.get(n)!)
}

/** Open the create modal on the manual path with the named photos staged. */
function stageManual(vm: VmAny, ...names: string[]) {
  vm.openCreate()
  vm.startManual()
  stage(vm, ...names)
}

describe('components/admin/AdminItemFormModal.vue', () => {
  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    analyzeMock.mockReset()
    analyzeMock.mockResolvedValue({})
    // UFileUpload renders an object-URL thumbnail for each selected image file,
    // and jsdom/Node's URL.createObjectURL rejects File instances built by this
    // file's makeFile() helper as "not a Blob" across realms. Stub it so the
    // preview path is harmless - a test environment shim, not a change to what
    // is being asserted.
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ---- openCreate / openEdit ----

  describe('openCreate / openEdit', () => {
    it('openCreate resets the form to defaults and opens the modal', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      vm.openEdit(makeItem({ id: 'old-id', name: 'Old Name' }))
      expect(vm.editingId).toBe('old-id')

      vm.openCreate()

      expect(vm.editingId).toBeNull()
      expect(vm.isEditing).toBe(false)
      expect(vm.form.name).toBe('')
    })

    it('openEdit populates the form from the item and opens the modal', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      vm.openEdit(makeItem({ id: 'i2' }))

      expect(vm.images.map(i => i.kind)).toEqual(['existing', 'existing'])
      expect(vm.images.map(i => i.url)).toEqual(['https://cdn.test/a.jpg', 'https://cdn.test/b.jpg'])
    })

    it('openEdit leaves the grid empty for an item with no usable image_path', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      vm.openEdit(makeItem({ image_path: null }))
      expect(vm.images).toEqual([])

      vm.openEdit(makeItem({ image_path: 'not-json' }))
      expect(vm.images).toEqual([])
    })

    it('openEdit falls back to empty description, "Good" condition, and undefined min_price when missing', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      expect(vm.canSubmit).toBe(false)
    })

    it('is false with a name but no price', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = 'Chair'
      expect(vm.canSubmit).toBe(false)
    })

    it('is false with a whitespace-only name', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.form.name = '   '
      vm.form.price = 50
      expect(vm.canSubmit).toBe(false)
    })

    it('is false when creating with name + price but no photos staged', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startManual()
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.images).toEqual([])
      expect(vm.canSubmit).toBe(false)
    })

    it('is true when creating with name + price + at least one staged photo', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'chair.png')
      vm.form.name = 'Chair'
      vm.form.price = 50

      expect(vm.canSubmit).toBe(true)
    })

    it('is true when editing with name + price and the item\'s stored photos', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(makeItem())
      vm.form.name = 'Chair'
      vm.form.price = 50
      expect(vm.images).toHaveLength(2)
      expect(vm.canSubmit).toBe(true)
    })

    it('is false when editing after every photo has been removed', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()

      expect(vm.step).toBe('choose')
      expect(vm.canSubmit).toBe(false)
    })

    it('startManual goes straight to the details step', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()
      vm.startManual()

      expect(vm.mode).toBe('manual')
      expect(vm.step).toBe('details')
      expect(analyzeMock).not.toHaveBeenCalled()
    })

    it('startAi goes to the photos step without analyzing anything yet', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      vm.openCreate()
      vm.startAi()

      expect(vm.mode).toBe('ai')
      expect(vm.step).toBe('photos')
      expect(analyzeMock).not.toHaveBeenCalled()
    })

    it('goBack returns from manual details to the choice screen', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny

      stageManual(vm, 'a.png')
      vm.goBack()

      expect(vm.step).toBe('choose')
    })

    it('goBack returns from AI details to the photos step, restoring the picker selection', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()

      await vm.detectAndContinue()

      expect(analyzeMock).not.toHaveBeenCalled()
      expect(vm.step).toBe('photos')
    })

    it('does not start a second analysis while one is already in flight', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]
      vm.isAnalyzing = true

      await vm.detectAndContinue()

      expect(analyzeMock).not.toHaveBeenCalled()
    })

    it('hands the selected photos to the analyzer and stages them in picked order', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      vm.startAi()
      vm.files = [makeFile()]

      analyzeMock.mockResolvedValueOnce({ condition: input })

      await vm.detectAndContinue()

      expect(vm.form.condition).toBe(expected)
    })

    it('warns but still advances to the details step when the analysis fails', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
  // ---- submitItem ----

  describe('submitItem', () => {
    it('is a no-op when canSubmit is false', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal)
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate() // no name/price/files yet

      await vm.submitItem()

      expect(callMock).not.toHaveBeenCalled() // the modal never fetches; it only writes
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
        const wrapper = await mountSuspended(AdminItemFormModal)
        const vm = wrapper.vm as unknown as VmAny
        await setupCreatable(vm)

        callMock.mockResolvedValueOnce({ id: 'new-1' }) // POST /items

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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
        const vm = wrapper.vm as unknown as VmAny
        stageManual(vm, 'a.png', 'b.png', 'c.png')
        vm.form.name = 'Guitar'
        vm.form.price = 250

        // Promote the last photo to the thumbnail slot.
        arrange(vm, 'c.png', 'a.png', 'b.png')

        callMock.mockResolvedValueOnce({})
        callMock.mockResolvedValueOnce([])

        await vm.submitItem()

        const createCall = callMock.mock.calls.find(([path, opts]) => path === '/items' && opts?.method === 'POST')
        const body = createCall![1].body as FormData
        expect((body.getAll('images') as File[]).map(f => f.name)).toEqual(['c.png', 'a.png', 'b.png'])
      })

      it('shows a "Create failed" toast with the API detail and keeps the modal open on failure', async () => {
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        vm.form.name = 'New Name'
        vm.form.price = 75

        callMock.mockResolvedValueOnce({}) // PUT

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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
        const vm = wrapper.vm as unknown as VmAny

        vm.openEdit(original)
        append(vm, 'fresh.png', 'newer.png')
        arrange(vm, 'fresh.png', 'https://cdn.test/a.jpg', 'newer.png', 'https://cdn.test/b.jpg')

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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
        const wrapper = await mountSuspended(AdminItemFormModal)
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
      const wrapper = await mountSuspended(AdminItemFormModal)
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
      await pending

      expect(vm.saving).toBe(false)
    })
  })
  // ---- modal body/footer template (UModal stubbed so its slot content renders inline) ----

  describe('modal body/footer fields (via UModalStub)', () => {
    it('creating: offers the manual and AI paths before showing any fields', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(item)
      vm.removeImage(0)
      vm.removeImage(0)
      await flushPromises()

      const submitBtn = wrapper.findAll('button').find(b => b.text() === 'Save changes')
      expect(submitBtn!.attributes('disabled')).toBeDefined()
    })

    it('typing into the Name/Description/Price/Minimum price fields updates the form via v-model', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')
      await flushPromises()

      const tiles = wrapper.findAll('[data-testid="image-tile"]')
      expect(tiles).toHaveLength(2)
      expect(tiles[0]!.text()).toContain('Thumbnail')
      expect(tiles[1]!.text()).toContain('2')
    })

    it('dragging and dropping a tile reorders photos and updates the thumbnail', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')
      await flushPromises()

      vm.dragIndex = 1
      vm.dropOn(0)

      expect(names(vm)).toEqual(['b.png', 'a.png'])
    })

    it('clicking a tile\'s remove button drops that photo', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'a.png', 'b.png')
      await flushPromises()

      const remove = wrapper.findAll('button').find(b => b.attributes('aria-label') === 'Remove photo')
      expect(remove).toBeTruthy()
      await remove!.trigger('click')

      expect(names(vm)).toEqual(['b.png'])
    })

    it('clicking Cancel in the footer closes the modal without submitting anything', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openCreate()
      await flushPromises()

      const cancelBtn = wrapper.findAll('button').find(b => b.text() === 'Cancel')
      expect(cancelBtn).toBeTruthy()
      await cancelBtn!.trigger('click')

      expect(vm.open).toBe(false)
      expect(callMock).not.toHaveBeenCalled() // the modal never fetches; it only writes
    })

    it('clicking the back button returns to the choice screen', async () => {
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
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
      const wrapper = await mountSuspended(AdminItemFormModal, {
        global: { stubs: { UModal: UModalStub } }
      })
      const vm = wrapper.vm as unknown as VmAny
      stageManual(vm, 'guitar.png')
      vm.form.name = 'Guitar'
      vm.form.price = 250
      await flushPromises()

      callMock.mockResolvedValueOnce({ id: 'new-1' }) // POST /items

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
      const wrapper = await mountSuspended(AdminItemFormModal, { global: { stubs: { UModal: UModalStub } } })
      const vm = wrapper.vm as unknown as VmAny
      vm.openEdit(original)
      await flushPromises()

      callMock.mockResolvedValueOnce({}) // PUT

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
