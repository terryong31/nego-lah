<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { AnalyzePatch, AnalyzeResult } from '~/composables/useItemAnalysis'

const { call } = useAdminApi()
const toast = useToast()
const { analyze, isAnalyzing, progress, stageMessage } = useItemAnalysis()

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

// A photo staged for upload. `url` is an object URL for the preview and must be
// revoked when the image leaves the list.
interface PendingImage {
  id: string
  file: File
  url: string
}

const { data: items, pending, refresh } = useAsyncData<Item[]>(
  'admin-items',
  () => call<Item[]>('/items'),
  { default: () => [] }
)

function firstImage(item: Item): string | undefined {
  if (!item.image_path) return undefined
  try {
    const map = JSON.parse(item.image_path)
    const urls = Object.values(map) as string[]
    return urls[0]
  } catch {
    return undefined
  }
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }) : '-'
}

// ---- Create / edit item modal ----
//
// Creating starts with a choice: fill the listing in by hand, or hand the
// photos to the AI and have it drafted for you. Either way you end up on the
// same details step, where the photo order (first = thumbnail) is set.
// Editing skips the choice entirely.
type Step = 'choose' | 'photos' | 'details'

const open = ref(false)
const saving = ref(false)
const step = ref<Step>('choose')
const mode = ref<'manual' | 'ai'>('manual')
const autofilled = ref(false)
const editingId = ref<string | null>(null)
const isEditing = computed(() => editingId.value != null)
const conditions = ['New', 'Like New', 'Good', 'Fair', 'Poor']
const conditionMap: Record<string, string> = {
  'new': 'New',
  'like new': 'Like New',
  'good': 'Good',
  'fair': 'Fair',
  'poor': 'Poor'
}
const form = reactive({
  name: '',
  description: '',
  condition: 'Good',
  price: undefined as number | undefined,
  min_price: undefined as number | undefined
})

// The AI step holds the raw picker selection; the details step owns the ordered
// list. They're synced on each step transition, so there's only ever one source
// of truth for a given step.
const files = ref<File[]>([])
const images = ref<PendingImage[]>([])
const dragIndex = ref<number | null>(null)
const addInput = useTemplateRef<HTMLInputElement>('addInput')

function makePending(file: File): PendingImage {
  return {
    id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
    file,
    // Guard for non-browser environments (SSR, test harnesses without the API).
    url: typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : ''
  }
}

function releaseImages() {
  for (const img of images.value) {
    if (img.url && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(img.url)
  }
  images.value = []
}

function moveImage(from: number, to: number) {
  if (to < 0 || to >= images.value.length) return
  const next = [...images.value]
  const [moved] = next.splice(from, 1)
  if (moved) next.splice(to, 0, moved)
  images.value = next
}

function removeImage(index: number) {
  const img = images.value[index]
  if (!img) return
  if (img.url && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(img.url)
  images.value = images.value.filter((_, i) => i !== index)
}

function dropOn(index: number) {
  if (dragIndex.value === null || dragIndex.value === index) return
  moveImage(dragIndex.value, index)
  dragIndex.value = null
}

function addImages(newFiles: File[]) {
  images.value = [...images.value, ...newFiles.map(makePending)]
}

function onAddFiles(event: Event) {
  const input = event.target as HTMLInputElement
  addImages(Array.from(input.files || []))
  input.value = ''
}

function onDropFiles(event: DragEvent) {
  // An in-grid reorder drag has no files attached — let dropOn handle it.
  const dropped = Array.from(event.dataTransfer?.files || []).filter(f => f.type.startsWith('image/'))
  if (dropped.length) addImages(dropped)
}

// ---- Choosing how to create ----

const createChoices = [
  {
    mode: 'manual' as const,
    icon: 'i-lucide-pencil-line',
    title: 'Fill in manually',
    description: 'Add your photos and write the listing yourself.'
  },
  {
    mode: 'ai' as const,
    icon: 'i-lucide-sparkles',
    title: 'Let AI detect it',
    description: 'Upload photos and have the name, description and price drafted for you.'
  }
]

const modalDescription = computed(() => {
  if (isEditing.value) return 'Update this listing.'
  if (step.value === 'choose') return 'How do you want to create this listing?'
  if (step.value === 'photos') return 'Add photos and let AI draft the listing.'
  return 'Review the details and set the photo order.'
})

function startManual() {
  mode.value = 'manual'
  step.value = 'details'
}

function startAi() {
  mode.value = 'ai'
  step.value = 'photos'
}

// ---- AI detect ----

function applyPatch(patch: AnalyzePatch) {
  // Only ever fills blanks — anything the admin already typed wins.
  if (patch.name && !form.name) form.name = patch.name
  if (patch.description && !form.description) form.description = patch.description
  if (patch.condition) {
    const mapped = conditionMap[patch.condition.toLowerCase()]
    if (mapped) form.condition = mapped
  }
  if (patch.price != null && !form.price) form.price = patch.price
}

function applyResult(res: AnalyzeResult) {
  applyPatch({
    name: res.name,
    description: res.description,
    condition: res.condition,
    price: res.market_data?.suggested_listing
  })
}

async function detectAndContinue() {
  if (files.value.length === 0 || isAnalyzing.value) return
  releaseImages()
  images.value = files.value.map(makePending)

  try {
    applyResult(await analyze(files.value, applyPatch))
    autofilled.value = true
    toast.add({ title: 'Analysis complete', description: 'Item details have been auto-filled', color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Analysis failed', description: e.data?.detail || e.message, color: 'warning' })
  } finally {
    // A failed analysis is not a dead end — the admin can still fill it in.
    step.value = 'details'
  }
}

function skipToManual() {
  releaseImages()
  images.value = files.value.map(makePending)
  mode.value = 'manual'
  step.value = 'details'
}

/** Back out of the current step: details -> photos (AI) or the choice screen. */
function goBack() {
  if (step.value === 'details' && mode.value === 'ai') {
    files.value = images.value.map(img => img.file)
    step.value = 'photos'
    return
  }
  step.value = 'choose'
}

// ---- Modal lifecycle ----

function resetForm() {
  form.name = ''
  form.description = ''
  form.condition = 'Good'
  form.price = undefined
  form.min_price = undefined
  files.value = []
  releaseImages()
  editingId.value = null
  step.value = 'choose'
  mode.value = 'manual'
  autofilled.value = false
}

// Closing by any route (Cancel, Escape, overlay, a finished submit) clears the
// staged photos, so object URLs are never leaked.
watch(open, (isOpen) => {
  if (!isOpen) resetForm()
})

function openCreate() {
  resetForm()
  open.value = true
}

function openEdit(item: Item) {
  resetForm()
  editingId.value = item.id
  form.name = item.name
  form.description = item.description || ''
  form.condition = item.condition || 'Good'
  form.price = item.price
  form.min_price = item.min_price ?? undefined
  open.value = true
}

// New images are only required when creating; editing keeps existing images.
const canSubmit = computed(() =>
  !isAnalyzing.value && !!form.name.trim() && form.price != null && (isEditing.value || images.value.length > 0)
)

async function submitItem() {
  if (!canSubmit.value) return
  saving.value = true
  try {
    if (isEditing.value) {
      await call(`/items/${editingId.value}`, {
        method: 'PUT',
        body: {
          name: form.name,
          description: form.description,
          condition: form.condition,
          price: form.price,
          min_price: form.min_price ?? null
        }
      })
      toast.add({ title: 'Item updated', color: 'success' })
    } else {
      const fd = new FormData()
      fd.append('name', form.name)
      fd.append('description', form.description)
      fd.append('condition', form.condition)
      fd.append('price', String(form.price))
      if (form.min_price != null) fd.append('min_price', String(form.min_price))
      // Order matters: the backend keys images by position, and the storefront
      // shows the first one as the thumbnail.
      for (const img of images.value) fd.append('images', img.file)

      await call('/items', { method: 'POST', body: fd })
      toast.add({ title: 'Item created', color: 'success' })
    }
    open.value = false
    await refresh()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: isEditing.value ? 'Update failed' : 'Create failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    saving.value = false
  }
}

// ---- Delete ----
const busy = ref<string | null>(null)
async function remove(item: Item) {
  busy.value = item.id
  try {
    await call(`/items/${item.id}`, { method: 'DELETE' })
    toast.add({ title: 'Item deleted', color: 'success' })
    await refresh()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Delete failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

const columns: TableColumn<Item>[] = [
  { accessorKey: 'name', header: 'Item' },
  { accessorKey: 'price', header: 'Price' },
  { accessorKey: 'condition', header: 'Condition' },
  { accessorKey: 'status', header: 'Status' },
  { accessorKey: 'created_at', header: 'Listed' },
  { id: 'actions', header: '' }
]
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted">
        {{ items.length }} item(s)
      </p>
      <div class="flex items-center gap-2">
        <UButton
          size="xs"
          variant="ghost"
          icon="i-lucide-refresh-cw"
          label="Refresh"
          :loading="pending"
          @click="refresh()"
        />
        <UButton
          size="xs"
          icon="i-lucide-plus"
          label="Upload item"
          @click="openCreate"
        />
      </div>
    </div>

    <UTable
      :columns="columns"
      :data="items"
      :loading="pending"
      :ui="{ td: 'py-2' }"
    >
      <template #name-cell="{ row }">
        <div class="flex items-center gap-3">
          <img
            v-if="firstImage(row.original)"
            :src="firstImage(row.original)"
            :alt="row.original.name"
            class="size-10 rounded-md object-cover bg-elevated"
          >
          <div
            v-else
            class="size-10 rounded-md bg-elevated flex items-center justify-center"
          >
            <UIcon
              name="i-lucide-image"
              class="size-4 text-muted"
            />
          </div>
          <p class="font-medium text-highlighted truncate max-w-50">
            {{ row.original.name }}
          </p>
        </div>
      </template>

      <template #price-cell="{ row }">
        <div>
          <p class="font-semibold">
            RM {{ (row.original.price || 0).toFixed(2) }}
          </p>
          <p
            v-if="row.original.min_price != null"
            class="text-xs text-muted"
          >
            min RM {{ row.original.min_price.toFixed(2) }}
          </p>
        </div>
      </template>

      <template #status-cell="{ row }">
        <UBadge
          :color="row.original.status === 'sold' ? 'neutral' : 'success'"
          variant="subtle"
          size="sm"
          class="capitalize"
        >
          {{ row.original.status }}
        </UBadge>
      </template>

      <template #created_at-cell="{ row }">
        <span class="text-sm text-muted">{{ formatDate(row.original.created_at) }}</span>
      </template>

      <template #actions-cell="{ row }">
        <div class="flex items-center justify-end gap-1">
          <UButton
            size="xs"
            color="neutral"
            variant="ghost"
            icon="i-lucide-pencil"
            @click="openEdit(row.original)"
          />
          <UButton
            size="xs"
            color="error"
            variant="soft"
            icon="i-lucide-trash-2"
            :loading="busy === row.original.id"
            @click="remove(row.original)"
          />
        </div>
      </template>
    </UTable>

    <!-- Create / edit modal -->
    <UModal
      v-model:open="open"
      :title="isEditing ? 'Edit item' : 'Upload item'"
      :description="modalDescription"
      :ui="{ content: 'max-w-lg' }"
    >
      <template #body>
        <div class="space-y-4">
          <!-- ===== Choose how to create ===== -->
          <template v-if="!isEditing && step === 'choose'">
            <button
              v-for="choice in createChoices"
              :key="choice.mode"
              type="button"
              class="flex w-full items-start gap-4 rounded-lg border border-default p-4 text-left transition-colors hover:border-primary hover:bg-elevated/50"
              @click="choice.mode === 'ai' ? startAi() : startManual()"
            >
              <span
                class="flex size-10 shrink-0 items-center justify-center rounded-lg"
                :class="choice.mode === 'ai' ? 'bg-primary/10 text-primary' : 'bg-elevated text-muted'"
              >
                <UIcon
                  :name="choice.icon"
                  class="size-5"
                />
              </span>
              <span class="space-y-1">
                <span class="block font-medium text-highlighted">{{ choice.title }}</span>
                <span class="block text-sm text-muted">{{ choice.description }}</span>
              </span>
            </button>
          </template>

          <!-- ===== AI: photos + detect ===== -->
          <template v-else-if="!isEditing && step === 'photos'">
            <UFormField
              label="Images"
              required
            >
              <UFileUpload
                v-model="files"
                multiple
                accept="image/*"
                layout="grid"
                :interactive="true"
                :disabled="isAnalyzing"
                label="Drop images here"
                description="PNG, JPG up to a few MB each"
                class="w-full min-h-32"
              />
            </UFormField>

            <div
              v-if="isAnalyzing"
              class="space-y-6 py-2"
            >
              <div class="space-y-2">
                <div class="flex justify-between text-sm font-medium text-highlighted">
                  <span>{{ stageMessage }}</span>
                  <span>{{ progress }}%</span>
                </div>
                <UProgress
                  :value="progress"
                  :max="100"
                />
              </div>

              <div class="space-y-4">
                <div class="space-y-2">
                  <USkeleton class="h-4 w-16" /><USkeleton class="h-9 w-full" />
                </div>
                <div class="space-y-2">
                  <USkeleton class="h-4 w-24" /><USkeleton class="h-20 w-full" />
                </div>
              </div>
            </div>

            <p
              v-else
              class="text-xs text-muted"
            >
              Photos are analyzed in parallel; you'll set their order in the next step.
            </p>
          </template>

          <!-- ===== Details + photo order ===== -->
          <template v-else>
            <UFormField
              v-if="!isEditing"
              label="Photos"
              required
              :hint="images.length ? `${images.length} photo(s) — drag to reorder` : 'First photo is the thumbnail'"
            >
              <div
                v-if="images.length === 0"
                class="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-accented p-6 text-center"
                @dragover.prevent
                @drop.prevent="onDropFiles"
              >
                <UIcon
                  name="i-lucide-image-plus"
                  class="size-6 text-muted"
                />
                <p class="text-sm text-muted">
                  Drop photos here, or
                </p>
                <UButton
                  size="xs"
                  color="neutral"
                  variant="subtle"
                  label="Choose files"
                  @click="addInput?.click()"
                />
              </div>

              <div
                v-else
                class="grid grid-cols-3 gap-2 sm:grid-cols-4"
                @dragover.prevent
                @drop.prevent="onDropFiles"
              >
                <div
                  v-for="(img, i) in images"
                  :key="img.id"
                  class="group relative aspect-square overflow-hidden rounded-lg border border-default bg-elevated"
                  :class="dragIndex === i ? 'opacity-40' : ''"
                  draggable="true"
                  data-testid="image-tile"
                  @dragstart="dragIndex = i"
                  @dragend="dragIndex = null"
                  @dragover.prevent
                  @drop.prevent="dropOn(i)"
                >
                  <img
                    :src="img.url"
                    :alt="`Photo ${i + 1}`"
                    class="size-full object-cover"
                  >
                  <span
                    v-if="i === 0"
                    class="absolute left-1 top-1 rounded bg-primary px-1.5 py-0.5 text-[10px] font-semibold text-inverted"
                  >Thumbnail</span>
                  <span
                    v-else
                    class="absolute left-1 top-1 rounded bg-default/80 px-1.5 py-0.5 text-[10px] font-semibold text-muted"
                  >{{ i + 1 }}</span>

                  <UButton
                    icon="i-lucide-x"
                    size="xs"
                    color="neutral"
                    variant="solid"
                    aria-label="Remove photo"
                    class="absolute right-1 top-1 rounded-full p-0.5 opacity-80"
                    @click="removeImage(i)"
                  />

                  <div class="absolute inset-x-1 bottom-1 flex justify-between">
                    <UButton
                      icon="i-lucide-chevron-left"
                      size="xs"
                      color="neutral"
                      variant="solid"
                      aria-label="Move photo earlier"
                      class="rounded-full p-0.5 opacity-80"
                      :disabled="i === 0"
                      @click="moveImage(i, i - 1)"
                    />
                    <UButton
                      icon="i-lucide-chevron-right"
                      size="xs"
                      color="neutral"
                      variant="solid"
                      aria-label="Move photo later"
                      class="rounded-full p-0.5 opacity-80"
                      :disabled="i === images.length - 1"
                      @click="moveImage(i, i + 1)"
                    />
                  </div>
                </div>

                <button
                  type="button"
                  class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-accented text-muted transition-colors hover:border-primary hover:text-primary"
                  @click="addInput?.click()"
                >
                  <UIcon
                    name="i-lucide-plus"
                    class="size-5"
                  />
                  <span class="text-[10px]">Add</span>
                </button>
              </div>

              <input
                ref="addInput"
                type="file"
                accept="image/*"
                multiple
                class="hidden"
                @change="onAddFiles"
              >
            </UFormField>

            <UAlert
              v-if="autofilled"
              icon="i-lucide-sparkles"
              color="primary"
              variant="subtle"
              title="Auto-filled by AI"
              description="Double-check the details and price before publishing."
            />

            <UFormField
              label="Name"
              required
            >
              <UInput
                v-model="form.name"
                placeholder="e.g. Fender Stratocaster"
                class="w-full"
              />
            </UFormField>

            <UFormField label="Description">
              <UTextarea
                v-model="form.description"
                :rows="3"
                placeholder="Condition notes, specs, what's included…"
                class="w-full"
              />
            </UFormField>

            <div class="grid grid-cols-2 gap-4">
              <UFormField label="Condition">
                <USelect
                  v-model="form.condition"
                  :items="conditions"
                  class="w-full"
                />
              </UFormField>
              <UFormField
                label="Price (RM)"
                required
              >
                <UInput
                  v-model.number="form.price"
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="0.00"
                  class="w-full"
                />
              </UFormField>
            </div>

            <UFormField
              label="Minimum price (RM)"
              hint="AI won't go below this"
            >
              <UInput
                v-model.number="form.min_price"
                type="number"
                min="0"
                step="0.01"
                placeholder="Optional"
                class="w-full"
              />
            </UFormField>
          </template>

          <p
            v-if="isEditing"
            class="text-xs text-muted"
          >
            Image editing isn't supported here — existing images are kept.
          </p>
        </div>
      </template>

      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <!-- The choice screen has nothing to submit — picking a card moves on. -->
          <UButton
            v-if="isEditing || step === 'choose'"
            color="neutral"
            variant="ghost"
            label="Cancel"
            :disabled="saving"
            @click="open = false"
          />
          <UButton
            v-else
            color="neutral"
            variant="ghost"
            icon="i-lucide-arrow-left"
            label="Back"
            :disabled="saving || isAnalyzing"
            @click="goBack"
          />

          <template v-if="!isEditing && step === 'photos'">
            <UButton
              color="neutral"
              variant="subtle"
              label="Skip, fill in manually"
              :disabled="isAnalyzing"
              @click="skipToManual"
            />
            <UButton
              icon="i-lucide-sparkles"
              label="Detect with AI"
              :loading="isAnalyzing"
              :disabled="files.length === 0"
              @click="detectAndContinue"
            />
          </template>

          <UButton
            v-else-if="isEditing || step === 'details'"
            :label="isEditing ? 'Save changes' : 'Create item'"
            :loading="saving"
            :disabled="!canSubmit"
            @click="submitItem"
          />
        </div>
      </template>
    </UModal>
  </div>
</template>
