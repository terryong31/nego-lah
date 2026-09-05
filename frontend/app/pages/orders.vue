<script setup lang="ts">
definePageMeta({
  middleware: 'auth'
})

const { call } = useApi()
const supabase = useSupabaseClient()
const user = useSupabaseUser()
const { t } = useI18n()

interface Order {
  item_name: string
  amount: number
  status: string
  created_at: string
}

const userId = computed(() => user.value?.id)

const { data: orders, pending } = useAsyncData<Order[]>(
  'user-orders',
  async () => {
    const { data: { session } } = await supabase.auth.getSession()
    const uid = session?.user?.id ?? user.value?.id
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

        <template #created_at-cell="{ row }">
          <span>{{ formatDate(row.original.created_at) }}</span>
        </template>
      </UTable>
    </div>
  </div>
</template>
