<script setup lang="ts">
definePageMeta({ layout: 'dashboard', middleware: 'admin-auth' })
useSeoMeta({ title: 'Dashboard · Admin', robots: 'noindex, nofollow' })

const { call } = useAdminApi()
const { t } = useI18n()

interface Summary {
  users: number
  conversations: number
  items_total: number
  items_available: number
  items_sold: number
  orders_total: number
  orders_pending: number
  orders_confirmed: number
  orders_shipped: number
  orders_delivered: number
  sales_total: number
}

interface Order {
  id: string
  item_name?: string
  amount: number
  status: string
  buyer_name?: string
  buyer_email?: string
  created_at: string
}

interface OrdersResponse {
  orders: Order[]
  stats: { total_orders: number, total_sales: number }
}

const { data: summary, pending: summaryPending, refresh: refreshSummary } = useAsyncData<Summary>(
  'admin-summary',
  () => call<Summary>('/summary'),
  {
    default: () => ({
      users: 0, conversations: 0, items_total: 0, items_available: 0, items_sold: 0,
      orders_total: 0, orders_pending: 0, orders_confirmed: 0, orders_shipped: 0,
      orders_delivered: 0, sales_total: 0
    })
  }
)

const { data: ordersData, pending: ordersPending, refresh: refreshOrders } = useAsyncData<OrdersResponse>(
  'admin-orders-recent',
  () => call<OrdersResponse>('/orders'),
  {
    default: () => ({
      orders: [],
      stats: { total_orders: 0, total_sales: 0 }
    })
  }
)

const isRefreshing = ref(false)
async function refreshAll() {
  isRefreshing.value = true
  try {
    await Promise.all([refreshSummary(), refreshOrders()])
  } finally {
    isRefreshing.value = false
  }
}

const money = (n: number) => `RM ${(n || 0).toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const aov = computed(() => {
  const totalOrders = summary.value.orders_total || 0
  if (totalOrders === 0) return 0
  return (summary.value.sales_total || 0) / totalOrders
})

// Top Executive Stats - no colored icon boxes or meaningless badges
const topStats = computed(() => [
  {
    label: t('admin.totalSales'),
    value: money(summary.value.sales_total),
    sublabel: `AOV: ${money(aov.value)}`,
    icon: 'i-lucide-badge-dollar-sign'
  },
  {
    label: t('admin.orders'),
    value: summary.value.orders_total,
    sublabel: 'All store orders',
    icon: 'i-lucide-shopping-bag',
    to: '/_console/orders'
  },
  {
    label: t('admin.activeChats'),
    value: summary.value.conversations,
    sublabel: 'Autonomous bargains',
    icon: 'i-lucide-messages-square',
    to: '/_console/chats'
  },
  {
    label: t('admin.users'),
    value: summary.value.users,
    sublabel: 'Registered community',
    icon: 'i-lucide-users',
    to: '/_console/users'
  }
])

// Orders fulfillment pipeline - clean stages without leading icon or badges for numbers
const pipelineStages = computed(() => [
  {
    label: t('admin.awaitingShipping'),
    count: summary.value.orders_pending,
    description: 'Awaiting buyer address',
    statusKey: 'pending_info'
  },
  {
    label: t('admin.readyToShip'),
    count: summary.value.orders_confirmed,
    description: 'Confirmed, ready to pack',
    statusKey: 'confirmed'
  },
  {
    label: t('admin.shipped'),
    count: summary.value.orders_shipped,
    description: 'En route with courier',
    statusKey: 'shipped'
  },
  {
    label: t('admin.delivered'),
    count: summary.value.orders_delivered,
    description: 'Received by customer',
    statusKey: 'delivered'
  }
])

// Recent 5 orders
const recentOrders = computed(() => (ordersData.value.orders || []).slice(0, 5))

function statusColor(s: string) {
  if (s === 'delivered') return 'success' as const
  if (s === 'shipped' || s === 'confirmed') return 'info' as const
  if (s === 'pending_info') return 'warning' as const
  if (s === 'refunded') return 'neutral' as const
  return 'error' as const
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-MY', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr
  }
}

// Floating Quick Actions menu items
const quickActionItems = computed(() => [
  [
    {
      label: 'Create New Item Listing',
      icon: 'i-lucide-plus',
      onSelect: () => navigateTo('/_console/items')
    },
    {
      label: 'Manage Shipping & Orders',
      icon: 'i-lucide-truck',
      onSelect: () => navigateTo('/_console/orders')
    },
    {
      label: 'View Registered Users',
      icon: 'i-lucide-users',
      onSelect: () => navigateTo('/_console/users')
    },
    {
      label: 'Inspect AI Conversations',
      icon: 'i-lucide-messages-square',
      onSelect: () => navigateTo('/_console/chats')
    }
  ]
])
</script>

<template>
  <UDashboardPanel id="admin-dashboard">
    <template #header>
      <UDashboardNavbar
        :title="$t('admin.dashboard')"
        icon="i-lucide-layout-dashboard"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UDashboardSearchButton class="w-60" />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <div class="space-y-8 pb-8">
        <!-- Subheader Toolbar with Live Sync & Refresh -->
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-xl font-bold text-highlighted tracking-tight">
              Store Overview
            </h1>
            <p class="text-sm text-muted">
              Marketplace telemetry and sales performance
            </p>
          </div>
          <div class="flex items-center gap-3">
            <span class="inline-flex items-center gap-1.5 text-sm text-muted">
              <span class="size-2 rounded-full bg-emerald-500 animate-pulse" />
              Live Sync
            </span>
            <UButton
              size="sm"
              variant="ghost"
              color="neutral"
              icon="i-lucide-refresh-cw"
              :loading="isRefreshing || summaryPending || ordersPending"
              :label="$t('admin.refresh')"
              @click="refreshAll"
            />
          </div>
        </div>

        <!-- 1. Top Executive KPI Grid -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <UCard
            v-for="s in topStats"
            :key="s.label"
            :class="s.to ? 'cursor-pointer hover:border-primary/40 hover:bg-elevated/40 transition-all' : ''"
            :ui="{ body: 'p-5' }"
            @click="s.to && navigateTo(s.to)"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="flex items-center gap-3.5 min-w-0">
                <UIcon
                  :name="s.icon"
                  class="size-8 text-muted shrink-0"
                />
                <div class="min-w-0">
                  <p class="text-sm font-semibold text-highlighted truncate">
                    {{ s.label }}
                  </p>
                  <USkeleton
                    v-if="summaryPending"
                    class="h-3.5 w-24 mt-1"
                  />
                  <p
                    v-else
                    class="text-xs text-muted truncate mt-0.5"
                  >
                    {{ s.sublabel }}
                  </p>
                </div>
              </div>

              <div class="text-right shrink-0">
                <USkeleton
                  v-if="summaryPending"
                  class="h-8 w-20 ml-auto"
                />
                <p
                  v-else
                  class="text-2xl font-bold text-highlighted tracking-tight"
                >
                  {{ s.value }}
                </p>
              </div>
            </div>
          </UCard>
        </div>

        <!-- 2. Actionable Orders Fulfillment Pipeline -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold text-highlighted">
              Orders pipeline
            </h2>
            <ULink
              to="/_console/orders"
              class="text-sm font-medium text-primary hover:underline flex items-center gap-1"
            >
              {{ $t('admin.viewAllOrders') }}
              <UIcon
                name="i-lucide-chevron-right"
                class="size-3.5"
              />
            </ULink>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <UCard
              v-for="stage in pipelineStages"
              :key="stage.label"
              class="cursor-pointer hover:bg-elevated/60 hover:border-primary/40 transition-all group"
              :ui="{ body: 'p-4 sm:p-5' }"
              @click="navigateTo('/_console/orders')"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="min-w-0">
                  <p class="text-sm font-semibold text-highlighted group-hover:text-primary transition-colors truncate">
                    {{ stage.label }}
                  </p>
                  <p class="text-xs text-muted truncate mt-0.5">
                    {{ stage.description }}
                  </p>
                </div>
                <USkeleton
                  v-if="summaryPending"
                  class="h-8 w-8 shrink-0"
                />
                <span
                  v-else
                  class="text-2xl font-bold text-highlighted shrink-0"
                >
                  {{ stage.count }}
                </span>
              </div>
            </UCard>
          </div>
        </div>

        <!-- 3. Primary Visual Analytics Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <!-- Sales & Revenue Trend Chart -->
          <div class="lg:col-span-7">
            <UCard :ui="{ body: 'p-4 sm:p-5' }">
              <AdminRevenueChart
                :orders="ordersData.orders"
                :pending="ordersPending"
              />
            </UCard>
          </div>

          <!-- Inventory Health Donut Chart -->
          <div class="lg:col-span-5">
            <UCard :ui="{ body: 'p-4 sm:p-5' }">
              <AdminDistributionChart
                :items-total="summary.items_total"
                :items-available="summary.items_available"
                :items-sold="summary.items_sold"
                :pending="summaryPending"
              />
            </UCard>
          </div>
        </div>

        <!-- 4. Operational Activity Stream & AI Telemetry -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <!-- Recent Orders Feed (Col 7) -->
          <div class="lg:col-span-7">
            <UCard :ui="{ body: 'p-5' }">
              <div class="flex items-center justify-between mb-4">
                <h3 class="text-base font-semibold text-highlighted">
                  {{ $t('admin.recentOrders') }}
                </h3>
              </div>

              <!-- Empty State -->
              <UEmpty
                v-if="!ordersPending && recentOrders.length === 0"
                icon="i-lucide-shopping-cart"
                :title="$t('admin.noOrdersYet')"
                description="When customers purchase listings or agree on AI bargains, transactions will populate here."
                variant="naked"
                class="py-10"
              />

              <!-- Loading Skeleton -->
              <div
                v-else-if="ordersPending"
                class="space-y-3"
              >
                <div
                  v-for="i in 4"
                  :key="i"
                  class="flex items-center justify-between p-3 rounded-lg bg-elevated/20 animate-pulse"
                >
                  <div class="space-y-1">
                    <USkeleton class="h-4 w-32" />
                    <USkeleton class="h-3 w-20" />
                  </div>
                  <USkeleton class="h-6 w-16" />
                </div>
              </div>

              <!-- Orders List -->
              <div
                v-else
                class="divide-y divide-default"
              >
                <div
                  v-for="order in recentOrders"
                  :key="order.id"
                  class="py-3 flex items-center justify-between gap-4 first:pt-0 last:pb-0 group cursor-pointer"
                  @click="navigateTo('/_console/orders')"
                >
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-highlighted truncate group-hover:text-primary transition-colors">
                      {{ order.item_name || `Order #${order.id.slice(0, 8)}` }}
                    </p>
                    <p class="text-xs text-muted truncate mt-0.5">
                      {{ order.buyer_name || order.buyer_email || 'Buyer' }} · {{ formatDate(order.created_at) }}
                    </p>
                  </div>

                  <div class="flex items-center gap-3 shrink-0">
                    <span class="text-sm font-bold text-highlighted">
                      {{ money(order.amount) }}
                    </span>
                    <UBadge
                      :color="statusColor(order.status)"
                      variant="subtle"
                      size="sm"
                    >
                      {{ order.status.replace('_', ' ') }}
                    </UBadge>
                  </div>
                </div>
              </div>
            </UCard>
          </div>

          <!-- AI Telemetry (Col 5) -->
          <div class="lg:col-span-5">
            <UCard :ui="{ body: 'p-5' }">
              <div class="flex items-center justify-between mb-3">
                <h3 class="text-base font-semibold text-highlighted">
                  {{ $t('admin.aiPulse') }}
                </h3>
              </div>

              <p class="text-sm text-muted mb-4 leading-relaxed">
                {{ $t('admin.aiPulseDesc') }}
              </p>

              <div class="grid grid-cols-2 gap-3 mb-4">
                <div class="p-3.5 rounded-lg bg-elevated/40 border border-default">
                  <p class="text-xs text-muted">
                    Active Chats
                  </p>
                  <p class="text-xl font-bold text-highlighted mt-0.5">
                    {{ summary.conversations }}
                  </p>
                </div>
                <div class="p-3.5 rounded-lg bg-elevated/40 border border-default">
                  <p class="text-xs text-muted">
                    Bargain Engine
                  </p>
                  <p class="text-sm font-medium text-muted mt-1">
                    Online
                  </p>
                </div>
              </div>

              <UButton
                block
                color="neutral"
                variant="outline"
                icon="i-lucide-messages-square"
                label="Inspect Live Conversations"
                size="md"
                to="/_console/chats"
              />
            </UCard>
          </div>
        </div>

        <!-- Floating Quick Actions Button at bottom-right of screen -->
        <div class="fixed bottom-6 right-6 z-40">
          <UDropdownMenu
            :items="quickActionItems"
            :content="{ side: 'top', align: 'end' }"
            :ui="{ content: 'w-56' }"
          >
            <UButton
              color="primary"
              size="lg"
              icon="i-lucide-zap"
              label="Quick Actions"
              class="rounded-full shadow-lg"
            />
          </UDropdownMenu>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>
