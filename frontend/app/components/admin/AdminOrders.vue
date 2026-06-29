<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'

const UButton = resolveComponent('UButton')

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

const STATUSES = ['pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded']
const statusItems = STATUSES.map(s => ({ label: s.replace('_', ' '), value: s }))
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
    toast.add({ title: `Order marked ${status.replace('_', ' ')}`, color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Update failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

async function remove(o: Order) {
  if (!confirm(`Delete this order for "${o.item_name || 'Untitled'}"?`)) return
  busy.value = o.id
  try {
    await call(`/orders/${o.id}`, { method: 'DELETE' })
    toast.add({ title: 'Order deleted', color: 'success' })
    await refresh()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Delete failed', description: e.data?.detail || e.message, color: 'error' })
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

const columns: TableColumn<Order>[] = [
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
  { accessorKey: 'item_name', header: 'Order' },
  { accessorKey: 'buyer_name', header: 'Buyer' },
  { accessorKey: 'amount', header: 'Amount' },
  { accessorKey: 'status', header: 'Status' },
  { accessorKey: 'created_at', header: 'Date' },
  { id: 'actions', header: '' }
]
</script>

<template>
  <div class="space-y-4">
    <div class="grid grid-cols-2 gap-4">
      <UCard :ui="{ body: 'p-4' }">
        <p class="text-xs text-muted">
          Total Orders
        </p>
        <p class="text-2xl font-bold text-highlighted">
          {{ data.stats.total_orders }}
        </p>
      </UCard>
      <UCard :ui="{ body: 'p-4' }">
        <p class="text-xs text-muted">
          Total Sales
        </p>
        <p class="text-2xl font-bold text-highlighted">
          RM {{ (data.stats.total_sales || 0).toFixed(2) }}
        </p>
      </UCard>
    </div>

    <div class="flex items-center justify-between">
      <p class="text-sm text-muted">
        {{ orders.length }} order(s)
      </p>
      <UButton
        size="xs"
        variant="ghost"
        icon="i-lucide-refresh-cw"
        label="Refresh"
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
            <div><span class="text-muted">Recipient:</span> {{ row.original.recipient_name || '—' }}</div>
            <div><span class="text-muted">Address:</span> <span class="whitespace-pre-line">{{ row.original.address || '—' }}</span></div>
            <div><span class="text-muted">Phone:</span> {{ row.original.phone || '—' }}</div>
            <div v-if="row.original.notes">
              <span class="text-muted">notes:</span> {{ row.original.notes }}
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
