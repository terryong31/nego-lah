<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { AnalyzePatch, AnalyzeResult } from '~/composables/useItemAnalysis'
import { adminItemSchema } from '~/utils/schemas'

const { t } = useI18n()
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
  translations?: Record<string, { name?: string, description?: string, condition?: string }>
}

// A photo staged in the grid. A `new` one carries the File to upload and an
// object URL for the preview, which must be revoked when it leaves the list; an
// `existing` one carries the listing's stored public URL, which must not be.
type PendingImage
  = | { id: string, kind: 'new', file: File, url: string }
    | { id: string, kind: 'existing', url: string }

const { data: items, pending, refresh } = useAsyncData<Item[]>(
  'admin-items',
  () => call<Item[]>('/items'),
  { default: () => [] }
)

// `image_path` is a {storage filename: public url} map whose insertion order is
// the display order, so the first value is the thumbnail.
function imageUrls(item: Item): string[] {
  if (!item.image_path) return []
  try {
    const map = JSON.parse(item.image_path)
    if (!map || typeof map !== 'object') return []
    return (Object.values(map) as string[]).filter(url => typeof url === 'string')
  } catch {
    return []
  }
}

function firstImage(item: Item): string | undefined {
  return imageUrls(item)[0]
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
const activeLang = ref<'en' | 'ms' | 'zh'>('en')
const langTabs = [
  { label: 'English', value: 'en' as const },
  { label: 'Bahasa Melayu', value: 'ms' as const },
  { label: '简体中文', value: 'zh' as const }
]
const langLabels: Record<'en' | 'ms' | 'zh', string> = {
  en: 'English',
  ms: 'Bahasa Melayu',
  zh: '简体中文'
}

const form = reactive({
  name: '',
  description: '',
  condition: 'Good',
  price: undefined as number | undefined,
  min_price: undefined as number | undefined,
  translations: {
    en: { name: '', description: '', condition: '' },
    ms: { name: '', description: '', condition: '' },
    zh: { name: '', description: '', condition: '' }
  } as Record<'en' | 'ms' | 'zh', { name: string, description: string, condition: string }>
})

const currentName = computed({
  get: () => {
    if (activeLang.value === 'en') return form.name
    return form.translations[activeLang.value]?.name || ''
  },
  set: (val: string) => {
    if (activeLang.value === 'en') {
      form.name = val
      form.translations.en.name = val
    } else {
      if (!form.translations[activeLang.value]) {
        form.translations[activeLang.value] = { name: '', description: '', condition: '' }
      }
      form.translations[activeLang.value].name = val
    }
  }
})

const currentDescription = computed({
  get: () => {
    if (activeLang.value === 'en') return form.description
    return form.translations[activeLang.value]?.description || ''
  },
  set: (val: string) => {
    if (activeLang.value === 'en') {
      form.description = val
      form.translations.en.description = val
    } else {
      if (!form.translations[activeLang.value]) {
        form.translations[activeLang.value] = { name: '', description: '', condition: '' }
      }
      form.translations[activeLang.value].description = val
    }
  }
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
    kind: 'new',
    file,
    // Guard for non-browser environments (SSR, test harnesses without the API).
    url: typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : ''
  }
}

function makeExisting(url: string): PendingImage {
  return { id: `existing-${url}`, kind: 'existing', url }
}

/** Revoke a preview URL — only ever the object URLs we created ourselves. */
function release(img: PendingImage) {
  if (img.kind === 'new' && img.url && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(img.url)
  }
}

function releaseImages() {
  for (const img of images.value) release(img)
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
  release(img)
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

function extractTrilingualData(raw: string | undefined): Record<string, { name?: string, description?: string, condition?: string }> | null {
  if (!raw || typeof raw !== 'string') return null
  const clean = raw.trim()
  const start = clean.indexOf('{')
  const end = clean.lastIndexOf('}')
  if (start === -1 || end <= start) return null
  const candidate = clean.slice(start, end + 1)
  try {
    const parsed = JSON.parse(candidate)
    if (parsed && typeof parsed === 'object' && (parsed.en || parsed.ms || parsed.zh)) {
      return parsed
    }
  } catch {
    try {
      const result: Record<string, { name?: string, description?: string, condition?: string }> = {}
      for (const lang of ['en', 'ms', 'zh']) {
        const langRegex = new RegExp(`"${lang}"\\s*:\\s*\\{([\\s\\S]*?)\\}(?=\\s*,\\s*"[a-z]{2}"|\\s*\\})`, 'i')
        const langMatch = langRegex.exec(candidate)
        if (langMatch && langMatch[1]) {
          const block = langMatch[1]
          const nameM = /"name"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"\w+"|\s*$)/.exec(block)
          const descM = /"description"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"\w+"|\s*$)/.exec(block)
          const condM = /"condition"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"\w+"|\s*$)/.exec(block)
          result[lang] = {
            name: nameM ? nameM[1]?.replace(/\\"/g, '"').replace(/\\n/g, '\n') : '',
            description: descM ? descM[1]?.replace(/\\"/g, '"').replace(/\\n/g, '\n') : '',
            condition: condM ? condM[1]?.replace(/\\"/g, '"') : ''
          }
        }
      }
      if (Object.keys(result).length > 0) return result
    } catch {
      // Fallback regex extraction failed
    }
  }
  return null
}

function applyPatch(patch: AnalyzePatch) {
  let translations = patch.translations
  let directDescription = patch.description

  if (!translations && patch.description) {
    const extracted = extractTrilingualData(patch.description)
    if (extracted) {
      translations = extracted
      directDescription = extracted.en?.description || ''
    }
  }

  if (translations) {
    for (const lang of ['en', 'ms', 'zh'] as const) {
      if (translations[lang]) {
        form.translations[lang] = {
          name: translations[lang]?.name || '',
          description: translations[lang]?.description || '',
          condition: translations[lang]?.condition || ''
        }
      }
    }
    if (translations.en?.name && !form.name) {
      form.name = translations.en.name
    }
    if (translations.en?.description && !form.description) {
      form.description = translations.en.description
    }
    if (translations.en?.condition) {
      const mapped = conditionMap[translations.en.condition.toLowerCase()]
      if (mapped) form.condition = mapped
    }
  }

  // Only ever fills blanks — anything the admin already typed wins.
  if (patch.name && !form.name) {
    form.name = patch.name
    if (!form.translations.en.name) form.translations.en.name = patch.name
  }
  if (directDescription && !form.description) {
    form.description = directDescription
    if (!form.translations.en.description) form.translations.en.description = directDescription
  }
  if (patch.condition) {
    const mapped = conditionMap[patch.condition.toLowerCase()]
    if (mapped) {
      form.condition = mapped
      if (!form.translations.en.condition) form.translations.en.condition = mapped
    }
  }
  if (patch.price != null && !form.price) form.price = patch.price
}

function applyResult(res: AnalyzeResult) {
  applyPatch({
    name: res.name,
    description: res.description,
    condition: res.condition,
    price: res.market_data?.suggested_listing,
    translations: res.translations
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

// When photos are uploaded in the photos step, immediately trigger AI detection
function onPhotosUploaded(uploadedFiles?: File[] | File | null) {
  if (Array.isArray(uploadedFiles)) {
    files.value = uploadedFiles
  }
  if (step.value === 'photos' && files.value.length > 0 && !isAnalyzing.value) {
    detectAndContinue()
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
    // The AI path is create-only, so every tile here is a newly picked file.
    files.value = images.value.flatMap(img => (img.kind === 'new' ? [img.file] : []))
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
  form.translations = {
    en: { name: '', description: '', condition: '' },
    ms: { name: '', description: '', condition: '' },
    zh: { name: '', description: '', condition: '' }
  }
  activeLang.value = 'en'
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
  form.condition = conditionMap[item.condition?.toLowerCase() ?? ''] || 'Good'
  form.price = item.price
  form.min_price = item.min_price ?? undefined
  if (item.translations) {
    for (const lang of ['en', 'ms', 'zh'] as const) {
      if (item.translations[lang]) {
        form.translations[lang] = {
          name: item.translations[lang]?.name || '',
          description: item.translations[lang]?.description || '',
          condition: item.translations[lang]?.condition || ''
        }
      }
    }
  }
  if (!form.translations.en.name) form.translations.en.name = form.name
  if (!form.translations.en.description) form.translations.en.description = form.description
  if (!form.translations.en.condition) form.translations.en.condition = form.condition
  images.value = imageUrls(item).map(makeExisting)
  step.value = 'details'
  mode.value = 'manual'
  open.value = true
}

const canSubmit = computed(() =>
  !isAnalyzing.value && !!form.name.trim() && form.price != null && images.value.length > 0
)

async function submitItem() {
  const validation = adminItemSchema.safeParse(form)
  if (!validation.success) {
    toast.add({
      title: 'Validation Error',
      description: validation.error.issues[0]?.message,
      color: 'error'
    })
    return
  }
  if (!canSubmit.value) return
  saving.value = true
  try {
    form.translations.en.name = form.name
    form.translations.en.description = form.description
    form.translations.en.condition = form.condition

    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('description', form.description)
    fd.append('condition', form.condition)
    fd.append('price', String(form.price))
    if (form.min_price != null) fd.append('min_price', String(form.min_price))
    fd.append('translations', JSON.stringify(form.translations))

    if (isEditing.value) {
      // One token per photo in display order: a kept photo's stored URL, or
      // "new:<n>" pointing at the nth file appended below. Photos left out are
      // dropped from the listing (and from storage) by the backend.
      const order: string[] = []
      let added = 0
      for (const img of images.value) {
        if (img.kind === 'new') {
          order.push(`new:${added++}`)
          fd.append('new_images', img.file)
        } else {
          order.push(img.url)
        }
      }
      fd.append('images_order', JSON.stringify(order))

      await call(`/items/${editingId.value}`, { method: 'PUT', body: fd })
      toast.add({ title: 'Item updated', color: 'success' })
    } else {
      // Order matters: the backend keys images by position, and the storefront
      // shows the first one as the thumbnail.
      for (const img of images.value) {
        if (img.kind === 'new') fd.append('images', img.file)
      }

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

const columns = computed<TableColumn<Item>[]>(() => [
  { accessorKey: 'name', header: t('admin.itemsSection.colName') },
  { accessorKey: 'price', header: t('admin.itemsSection.colPrice') },
  { accessorKey: 'condition', header: t('admin.itemsSection.colStatus') },
  { accessorKey: 'status', header: t('admin.itemsSection.colStatus') },
  { accessorKey: 'created_at', header: t('admin.itemsSection.colCreated') },
  { id: 'actions', header: '' }
])

defineExpose({
  skipToManual
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted">
        {{ items.length }} item(s)
      </p>
      <div class="flex items-center gap-2">
        <UButton
          size="sm"
          variant="ghost"
          icon="i-lucide-refresh-cw"
          :label="$t('admin.ordersSection.refresh')"
          :loading="pending"
          @click="refresh()"
        />
        <UButton
          size="sm"
          icon="i-lucide-plus"
          :label="$t('admin.itemsSection.uploadItem')"
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
      <template #empty>
        <UEmpty
          icon="i-lucide-tag"
          :title="$t('admin.itemsSection.emptyTitle')"
          :description="$t('admin.itemsSection.emptyDesc')"
          variant="naked"
          :actions="[
            {
              icon: 'i-lucide-plus',
              label: t('admin.itemsSection.uploadItem'),
              color: 'primary',
              onClick: openCreate
            }
          ]"
          class="py-6"
        />
      </template>

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
      :description="modalDescription"
      :ui="{ content: 'max-w-lg' }"
    >
      <template #title>
        <div class="flex items-center gap-2">
          <UButton
            v-if="!isEditing && step !== 'choose'"
            icon="i-lucide-arrow-left"
            color="neutral"
            variant="ghost"
            size="sm"
            class="-ms-1.5"
            aria-label="Back"
            :disabled="saving || isAnalyzing"
            @click="goBack"
          />
          <span>{{ isEditing ? 'Edit item' : 'Upload item' }}</span>
        </div>
      </template>

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
                @update:model-value="onPhotosUploaded"
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
                  :model-value="progress"
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

            <!-- Translation language tabs -->
            <div class="space-y-1.5">
              <div class="text-xs font-semibold text-muted uppercase tracking-wider">
                Listing Language
              </div>
              <UTabs
                v-model="activeLang"
                :items="langTabs"
                variant="link"
                color="primary"
                :content="false"
                class="w-full"
                :ui="{
                  list: 'border-b border-default'
                }"
              />
            </div>

            <UFormField
              :label="activeLang === 'en' ? 'Name' : `Name (${langLabels[activeLang]})`"
              :required="activeLang === 'en'"
            >
              <UInput
                v-model="currentName"
                :placeholder="activeLang === 'en' ? 'e.g. Fender Stratocaster' : 'Translated item name'"
                class="w-full"
              />
            </UFormField>

            <UFormField :label="activeLang === 'en' ? 'Description' : `Description (${langLabels[activeLang]})`">
              <UTextarea
                v-model="currentDescription"
                :rows="3"
                :placeholder="activeLang === 'en' ? 'Condition notes, specs, what\'s included…' : 'Translated description…'"
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
        </div>
      </template>

      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="ghost"
            label="Cancel"
            :disabled="saving"
            @click="() => { open = false }"
          />

          <UButton
            v-if="isEditing || step === 'details'"
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
