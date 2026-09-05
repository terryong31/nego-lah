<script setup lang="ts">
import { computed, h, ref, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'

const UButton = resolveComponent('UButton')

const { t } = useI18n()
const { call } = useAdminApi()
const toast = useToast()

interface Order {
  id: string
  item_name: string
  amount: number
  status: string
  buyer_name?: string
  buyer_email?: string
  recipient_name?: string
  address?: string
  phone?: string
  notes?: string
  created_at: string
}
interface OrdersResponse {
  orders: Order[]
  stats: { total_orders: number, total_sales: number }
}

const { data, pending, refresh } = useAsyncData<OrdersResponse>(
  'admin-orders',
  () => call<OrdersResponse>('/orders'),
  { default: () => ({ orders: [], stats: { total_orders: 0, total_sales: 0 } }) }
)

const orders = computed(() => data.value.orders)

const statusItems = computed(() => [
  { label: t('admin.ordersSection.statusPendingInfo'), value: 'pending_info' },
  { label: t('admin.ordersSection.statusConfirmed'), value: 'confirmed' },
  { label: t('admin.ordersSection.statusShipped'), value: 'shipped' },
  { label: t('admin.ordersSection.statusDelivered'), value: 'delivered' },
  { label: t('admin.ordersSection.statusCancelled'), value: 'cancelled' },
  { label: t('admin.ordersSection.statusRefunded'), value: 'refunded' }
])
const busy = ref<string | null>(null)

// Native Nuxt UI Expanded row tracking
const expanded = ref({})

function statusColor(s: string) {
  if (s === 'delivered') return 'success' as const
  if (s === 'shipped' || s === 'confirmed') return 'info' as const
  if (s === 'pending_info') return 'warning' as const
  if (s === 'refunded') return 'neutral' as const
  return 'error' as const
}

async function changeStatus(o: Order, status: string) {
  if (status === o.status) return
  busy.value = o.id
  try {
    await call(`/orders/${o.id}/status`, { method: 'PUT', body: { status } })
    o.status = status
    toast.add({ title: t('admin.ordersSection.markedSuccess', { status: status.replace('_', ' ') }), color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('admin.ordersSection.updateFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

async function remove(o: Order) {
  if (!confirm(t('admin.ordersSection.deleteConfirm', { name: o.item_name || 'Untitled' }))) return
  busy.value = o.id
  try {
    await call(`/orders/${o.id}`, { method: 'DELETE' })
    toast.add({ title: t('admin.ordersSection.deletedSuccess'), color: 'success' })
    await refresh()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('admin.ordersSection.deleteFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }) : '-'
}

function hasShippingInfo(o: Order) {
  return o.recipient_name || o.address || o.phone
}

const columns = computed<TableColumn<Order>[]>(() => [
  {
    id: 'expand',
    cell: ({ row }) => h(UButton, {
      'color': 'neutral',
      'variant': 'ghost',
      'icon': 'i-lucide-chevron-right',
      'square': true,
      'aria-label': 'Expand',
      'ui': {
        leadingIcon: ['transition-transform', row.getIsExpanded() ? 'duration-200 rotate-90' : '']
      },
      'onClick': () => row.toggleExpanded()
    })
  },
  { accessorKey: 'item_name', header: t('admin.ordersSection.colOrder') },
  { accessorKey: 'buyer_name', header: t('admin.ordersSection.colBuyer') },
  { accessorKey: 'amount', header: t('admin.ordersSection.colAmount') },
  { accessorKey: 'status', header: t('admin.ordersSection.colStatus') },
  { accessorKey: 'created_at', header: t('admin.ordersSection.colDate') },
  { id: 'actions', header: '' }
])
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted">
        {{ $t('admin.ordersSection.count', { n: orders.length }) }}
      </p>
      <UButton
        size="xs"
        variant="ghost"
        icon="i-lucide-refresh-cw"
        :label="$t('admin.ordersSection.refresh')"
        :loading="pending"
        @click="refresh()"
      />
    </div>

    <UTable
      v-model:expanded="expanded"
      :columns="columns"
      :data="orders"
      :loading="pending"
      :ui="{ td: 'py-2', tr: 'data-[expanded=true]:bg-elevated/50' }"
    >
      <template #empty>
        <UEmpty
          icon="i-lucide-package"
          :title="$t('admin.ordersSection.emptyTitle')"
          :description="$t('admin.ordersSection.emptyDesc')"
          variant="naked"
          class="py-6"
        />
      </template>

      <template #item_name-cell="{ row }">
        <p class="font-medium text-highlighted truncate max-w-50">
          {{ row.original.item_name || 'Untitled' }}
        </p>
      </template>

      <template #buyer_name-cell="{ row }">
        <div class="min-w-0">
          <p class="text-sm text-default truncate">
            {{ row.original.buyer_name || 'Unknown' }}
          </p>
          <p class="text-xs text-muted truncate">
            {{ row.original.buyer_email || '—' }}
          </p>
        </div>
      </template>

      <template #amount-cell="{ row }">
        <span class="font-semibold">RM {{ (row.original.amount || 0).toFixed(2) }}</span>
      </template>

      <template #status-cell="{ row }">
        <UBadge
          :color="statusColor(row.original.status)"
          variant="subtle"
          size="sm"
          class="capitalize"
        >
          {{ row.original.status?.replace('_', ' ') }}
        </UBadge>
      </template>

      <template #created_at-cell="{ row }">
        <span class="text-sm text-muted">{{ formatDate(row.original.created_at) }}</span>
      </template>

      <template #actions-cell="{ row }">
        <div class="flex items-center justify-end gap-2">
          <USelect
            :model-value="row.original.status"
            :items="statusItems"
            size="sm"
            class="w-36"
            :disabled="busy === row.original.id"
            @update:model-value="(s: string) => changeStatus(row.original, s)"
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

      <template #expanded="{ row }">
        <div>
          <p class="text-sm font-semibold text-highlighted mb-2">
            Shipping Details
          </p>
          <div class="flex flex-col text-sm text-default space-y-1">
            <div><span class="text-muted">{{ $t('admin.ordersSection.recipient') }}:</span> {{ row.original.recipient_name || '—' }}</div>
            <div><span class="text-muted">{{ $t('admin.ordersSection.address') }}:</span> <span class="whitespace-pre-line">{{ row.original.address || '—' }}</span></div>
            <div><span class="text-muted">{{ $t('admin.ordersSection.phone') }}:</span> {{ row.original.phone || '—' }}</div>
            <div v-if="row.original.notes">
              <span class="text-muted">{{ $t('admin.ordersSection.notes') }}:</span> {{ row.original.notes }}
            </div>
          </div>
          <p
            v-if="!hasShippingInfo(row.original)"
            class="text-sm text-muted italic mt-2"
          >
            No shipping info collected yet.
          </p>
        </div>
      </template>
    </UTable>
  </div>
</template>
