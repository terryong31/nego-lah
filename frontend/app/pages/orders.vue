<script setup lang="ts">
import { resolveUserId } from '~/utils/auth'

definePageMeta({
  middleware: 'auth'
})

const { call } = useApi()
const { user } = useAuth()
const { t } = useI18n()

interface Order {
  item_name: string
  amount: number
  status: string
  created_at: string
  // SPEC-069: filled by the console when the seller posts the parcel. Null on
  // anything that has not shipped, and `tracking_url` is null on its own
  // whenever the carrier is not one the backend registry knows how to link to.
  courier?: string | null
  tracking_number?: string | null
  tracking_url?: string | null
  shipped_at?: string | null
}

const userId = computed(() => resolveUserId(user.value))

const { data: orders, pending } = useAsyncData<Order[]>(
  'user-orders',
  async () => {
    const uid = resolveUserId(user.value)
    if (!uid) return []
    const res = await call<{ orders: Order[] }>(`/payment/orders/user/${uid}`)
    return res.orders ?? []
  },
  {
    default: () => [],
    server: false,
    watch: [userId]
  }
)

const columns = computed(() => [
  { accessorKey: 'item_name', header: t('orders.colItem') },
  { accessorKey: 'amount', header: t('orders.colPrice') },
  { accessorKey: 'status', header: t('orders.colStatus') },
  { accessorKey: 'tracking_number', header: t('orders.colTracking') },
  { accessorKey: 'created_at', header: t('orders.colDate') }
])

function getStatusColor(status: string) {
  const s = status?.toLowerCase()
  if (s === 'completed' || s === 'delivered') return 'success' as const
  if (s === 'paid' || s === 'shipped') return 'info' as const
  if (s === 'pending') return 'warning' as const
  if (s === 'refunded') return 'neutral' as const
  return 'error' as const
}

/** The carrier line for an order, or null when there is nothing to show yet. */
function trackingLabel(order: Order) {
  const parts = [order.courier, order.tracking_number].filter(Boolean)
  return parts.length ? parts : null
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('en-MY', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-highlighted">
        {{ $t('orders.purchaseHistory') }}
      </h1>
    </div>

    <USeparator />

    <div
      v-if="pending"
      class="space-y-4"
    >
      <USkeleton class="h-10 w-full" />
      <USkeleton
        v-for="i in 3"
        :key="i"
        class="h-12 w-full"
      />
    </div>

    <UEmpty
      v-else-if="orders.length === 0"
      icon="i-lucide-shopping-bag"
      :title="$t('orders.noOrdersYet')"
      :description="$t('orders.noOrdersDesc')"
      :actions="[{
        label: $t('orders.browseItems'),
        to: '/',
        color: 'primary'
      }]"
      variant="naked"
      class="py-16"
    />

    <div
      v-else
      data-tour="orders-table"
      class="overflow-x-auto"
    >
      <UTable
        :columns="columns"
        :data="orders"
      >
        <template #amount-cell="{ row }">
          <span class="font-semibold">RM {{ row.original.amount?.toFixed(2) }}</span>
        </template>

        <template #status-cell="{ row }">
          <UBadge
            :color="getStatusColor(row.original.status)"
            variant="subtle"
            class="capitalize"
          >
            {{ row.original.status?.replace(/_/g, ' ') }}
          </UBadge>
        </template>

        <template #tracking_number-cell="{ row }">
          <ULink
            v-if="row.original.tracking_url && trackingLabel(row.original)"
            :to="row.original.tracking_url"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1.5 text-primary"
          >
            <span class="text-sm">{{ trackingLabel(row.original)!.join(' \u00b7 ') }}</span>
            <UIcon
              name="i-lucide-external-link"
              class="size-3.5 shrink-0"
            />
          </ULink>
          <span
            v-else-if="trackingLabel(row.original)"
            class="text-sm text-muted"
          >{{ trackingLabel(row.original)!.join(' \u00b7 ') }}</span>
          <span
            v-else
            class="text-muted"
          >&mdash;</span>
        </template>

        <template #created_at-cell="{ row }">
          <span>{{ formatDate(row.original.created_at) }}</span>
        </template>
      </UTable>
    </div>
  </div>
</template>
