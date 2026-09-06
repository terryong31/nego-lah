<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { AdminItem } from '~/utils/adminItem'
import { itemThumbnail } from '~/utils/adminItem'

// The listings table. Creating and editing live in <AdminItemFormModal>, which
// owns all of that form state; this component only lists, deletes, and tells
// the modal to open (SPEC-037).

const { t } = useI18n()
const { call } = useAdminApi()
const toast = useToast()

const formModal = useTemplateRef<{
  openCreate: () => void
  openEdit: (item: AdminItem) => void
}>('formModal')

const { data: items, pending, refresh } = useAsyncData<AdminItem[]>(
  'admin-items',
  () => call<AdminItem[]>('/items'),
  { default: () => [] }
)

function formatDate(d: string) {
  return d ? new Date(d).toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }) : '-'
}

// ---- Delete ----
const busy = ref<string | null>(null)
async function remove(item: AdminItem) {
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

const columns = computed<TableColumn<AdminItem>[]>(() => [
  { accessorKey: 'name', header: t('admin.itemsSection.colName') },
  { accessorKey: 'price', header: t('admin.itemsSection.colPrice') },
  { accessorKey: 'condition', header: t('admin.itemsSection.colStatus') },
  { accessorKey: 'status', header: t('admin.itemsSection.colStatus') },
  { accessorKey: 'created_at', header: t('admin.itemsSection.colCreated') },
  { id: 'actions', header: '' }
])
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
          @click="formModal?.openCreate()"
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
              onClick: () => formModal?.openCreate()
            }
          ]"
          class="py-6"
        />
      </template>

      <template #name-cell="{ row }">
        <div class="flex items-center gap-3">
          <img
            v-if="itemThumbnail(row.original)"
            :src="itemThumbnail(row.original)"
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
            @click="formModal?.openEdit(row.original)"
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

    <AdminItemFormModal
      ref="formModal"
      @saved="refresh()"
    />
  </div>
</template>
