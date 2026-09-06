import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import AdminItems from '~/components/admin/AdminItems.vue'
import AdminItemFormModal from '~/components/admin/AdminItemFormModal.vue'

// The listings table. Since SPEC-037 this component only lists, deletes, and
// hands a row to <AdminItemFormModal>; every test about the create/edit form
// itself lives in AdminItemFormModal.test.ts, and photo staging in
// tests/composables/useItemImages.test.ts.

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

/** The list component's own bindings, reached without `any` everywhere. */
interface VmAny {
  items: Item[]
  pending: boolean
  busy: string | null
  remove: (item: Item) => Promise<void>
  formatDate: (d: string) => string
}

/** The slice of the child modal these tests assert against. */
interface ModalVm {
  open: boolean
  editingId: string | null
  form: { name: string }
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
  // ---- template bindings: header/table buttons + handing rows to the modal ----
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

    it('clicking a row\'s edit (pencil) button opens the form modal on that row', async () => {
      const item = makeItem({ id: 'row-1', name: 'Lamp' })
      callMock.mockResolvedValueOnce([item])
      const wrapper = await mountSuspended(AdminItems)

      const editBtn = wrapper.findAllComponents({ name: 'UButton' }).find(b => b.props('icon') === 'i-lucide-pencil')
      expect(editBtn).toBeTruthy()
      await editBtn!.trigger('click')

      // The form lives in the child component now (SPEC-037); the list's job
      // is only to hand it the row. What the modal then does with it is
      // covered by AdminItemFormModal.test.ts.
      const modal = wrapper.findComponent(AdminItemFormModal)
      const modalVm = modal.vm as unknown as ModalVm
      expect(modalVm.open).toBe(true)
      expect(modalVm.editingId).toBe('row-1')
      expect(modalVm.form.name).toBe('Lamp')
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
      await flushPromises()

      const empty = wrapper.findComponent({ name: 'UEmpty' })
      expect(empty.exists()).toBe(true)
      expect(empty.props('title')).toBe('No items found')

      const uploadBtn = empty.findComponent({ name: 'UButton' })
      expect(uploadBtn.exists()).toBe(true)
      expect(uploadBtn.props('label')).toBe('Upload item')

      await uploadBtn.trigger('click')
      await flushPromises()
      const modalVm = wrapper.findComponent(AdminItemFormModal).vm as unknown as ModalVm
      expect(modalVm.open).toBe(true)
      expect(modalVm.editingId).toBeNull()
    })
  })
})
