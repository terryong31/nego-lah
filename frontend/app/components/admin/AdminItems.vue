<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'

const { call } = useAdminApi()
const toast = useToast()

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
const open = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const isEditing = computed(() => editingId.value != null)
const conditions = ['New', 'Like New', 'Good', 'Fair', 'Poor']
const form = reactive({
  name: '',
  description: '',
  condition: 'Good',
  price: undefined as number | undefined,
  min_price: undefined as number | undefined
})
const files = ref<File[]>([])

function resetForm() {
  form.name = ''
  form.description = ''
  form.condition = 'Good'
  form.price = undefined
  form.min_price = undefined
  files.value = []
  editingId.value = null
}

function openCreate() {
  resetForm()
  open.value = true
}

function openEdit(item: Item) {
  editingId.value = item.id
  form.name = item.name
  form.description = item.description || ''
  form.condition = item.condition || 'Good'
  form.price = item.price
  form.min_price = item.min_price ?? undefined
  files.value = []
  open.value = true
}

// New images are only required when creating; editing keeps existing images.
const canSubmit = computed(() =>
  !!form.name.trim() && form.price != null && (isEditing.value || files.value.length > 0)
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
      for (const f of files.value) fd.append('images', f)

      await call('/items', { method: 'POST', body: fd })
      toast.add({ title: 'Item created', color: 'success' })
    }
    open.value = false
    resetForm()
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
      :description="isEditing ? 'Update this listing.' : 'Create a new listing.'"
      :ui="{ content: 'max-w-lg' }"
    >
      <template #body>
        <div class="space-y-4">
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
              placeholder="optional"
              class="w-full"
            />
          </UFormField>

          <UFormField
            v-if="!isEditing"
            label="Images"
            required
          >
            <UFileUpload
              v-model="files"
              multiple
              accept="image/*"
              layout="grid"
              :interactive="true"
              label="Drop images here"
              description="PNG, JPG up to a few MB each"
              class="w-full min-h-32"
            />
          </UFormField>
          <p
            v-else
            class="text-xs text-muted"
          >
            Image editing isn't supported here — existing images are kept.
          </p>
        </div>
      </template>

      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            label="Cancel"
            :disabled="saving"
            @click="open = false"
          />
          <UButton
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
