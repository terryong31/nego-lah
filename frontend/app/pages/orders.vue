<script setup lang="ts">
definePageMeta({
  middleware: 'auth'
})

const { call } = useApi()
const supabase = useSupabaseClient()
const user = useSupabaseUser()

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
    // Resolve the id from the live session rather than the reactive
    // `useSupabaseUser` ref: on a hard refresh the ref can be truthy while its
    // `id` is still undefined during hydration, which made this page render
    // "No Orders Yet" even when orders exist. The `watch` below re-runs this
    // once the session hydrates.
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

const columns = [
  { accessorKey: 'item_name', header: 'Item Name' },
  { accessorKey: 'amount', header: 'Price (RM)' },
  { accessorKey: 'status', header: 'Status' },
  { accessorKey: 'created_at', header: 'Purchased On' }
]

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
        Purchase History
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

    <div
      v-else-if="orders.length === 0"
      class="flex flex-col items-center justify-center py-20 text-center"
    >
      <UIcon
        name="i-lucide-shopping-bag"
        class="size-16 text-muted mb-4"
      />
      <h3 class="text-lg font-semibold text-highlighted">
        No Orders Yet
      </h3>
      <p class="text-sm text-muted mt-1 max-w-xs">
        Bargain with our AI model and secure a deal to start purchasing!
      </p>
      <UButton
        label="Explore Storefront"
        to="/"
        class="mt-4"
      />
    </div>

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
            {{ row.original.status }}
          </UBadge>
        </template>

        <template #created_at-cell="{ row }">
          <span>{{ formatDate(row.original.created_at) }}</span>
        </template>
      </UTable>
    </div>
  </div>
</template>
