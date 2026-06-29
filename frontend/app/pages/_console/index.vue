<script setup lang="ts">
definePageMeta({ layout: 'dashboard', middleware: 'admin-auth' })
useSeoMeta({ title: 'Dashboard · Admin', robots: 'noindex, nofollow' })

const { call } = useAdminApi()

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

const { data, pending, refresh } = useAsyncData<Summary>(
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

const money = (n: number) => `RM ${(n || 0).toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Headline stats
const stats = computed(() => [
  { label: 'Total sales', value: money(data.value.sales_total), icon: 'i-lucide-dollar-sign', color: 'text-primary' },
  { label: 'Orders', value: data.value.orders_total, icon: 'i-lucide-package', to: '/_console/orders' },
  { label: 'Users', value: data.value.users, icon: 'i-lucide-users', to: '/_console/users' },
  { label: 'Active chats', value: data.value.conversations, icon: 'i-lucide-messages-square', to: '/_console/chats' }
])

// Orders that need attention
const attention = computed(() => [
  { label: 'Awaiting shipping info', value: data.value.orders_pending, iconClass: 'text-warning', icon: 'i-lucide-clock' },
  { label: 'Ready to ship', value: data.value.orders_confirmed, iconClass: 'text-info', icon: 'i-lucide-box' },
  { label: 'Shipped', value: data.value.orders_shipped, iconClass: 'text-info', icon: 'i-lucide-truck' },
  { label: 'Delivered', value: data.value.orders_delivered, iconClass: 'text-success', icon: 'i-lucide-check' }
])
</script>

<template>
  <UDashboardPanel id="admin-dashboard">
    <template #header>
      <UDashboardNavbar
        title="Dashboard"
        icon="i-lucide-layout-dashboard"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UButton
            size="xs"
            variant="ghost"
            icon="i-lucide-refresh-cw"
            label="Refresh"
            :loading="pending"
            @click="refresh()"
          />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <div class="space-y-6">
        <!-- Headline metrics -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <UCard
            v-for="s in stats"
            :key="s.label"
            :class="s.to ? 'cursor-pointer hover:bg-elevated/50 transition-colors' : ''"
            :ui="{ body: 'p-4' }"
            @click="s.to && navigateTo(s.to)"
          >
            <div class="flex items-center justify-between">
              <p class="text-xs text-muted">
                {{ s.label }}
              </p>
              <UIcon
                :name="s.icon"
                class="size-4 text-dimmed"
              />
            </div>
            <USkeleton
              v-if="pending"
              class="h-8 w-20 mt-2"
            />
            <p
              v-else
              class="text-2xl font-bold mt-1"
              :class="s.color || 'text-highlighted'"
            >
              {{ s.value }}
            </p>
          </UCard>
        </div>

        <!-- Orders pipeline -->
        <div>
          <h2 class="text-sm font-semibold text-highlighted mb-3">
            Orders pipeline
          </h2>
          <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <UCard
              v-for="a in attention"
              :key="a.label"
              :ui="{ body: 'p-4' }"
            >
              <div class="flex items-center gap-3">
                <div class="flex items-center justify-center size-9 rounded-lg bg-elevated">
                  <UIcon
                    :name="a.icon"
                    class="size-4"
                    :class="a.iconClass"
                  />
                </div>
                <div>
                  <USkeleton
                    v-if="pending"
                    class="h-6 w-10"
                  />
                  <p
                    v-else
                    class="text-xl font-bold text-highlighted leading-tight"
                  >
                    {{ a.value }}
                  </p>
                  <p class="text-xs text-muted">
                    {{ a.label }}
                  </p>
                </div>
              </div>
            </UCard>
          </div>
        </div>

        <!-- Inventory -->
        <div>
          <h2 class="text-sm font-semibold text-highlighted mb-3">
            Inventory
          </h2>
          <div class="grid grid-cols-2 lg:grid-cols-3 gap-4">
            <UCard :ui="{ body: 'p-4' }">
              <p class="text-xs text-muted">
                Listings
              </p>
              <USkeleton
                v-if="pending"
                class="h-7 w-16 mt-1"
              />
              <p
                v-else
                class="text-xl font-bold text-highlighted mt-1"
              >
                {{ data.items_total }}
              </p>
            </UCard>
            <UCard :ui="{ body: 'p-4' }">
              <p class="text-xs text-muted">
                Available
              </p>
              <USkeleton
                v-if="pending"
                class="h-7 w-16 mt-1"
              />
              <p
                v-else
                class="text-xl font-bold text-success mt-1"
              >
                {{ data.items_available }}
              </p>
            </UCard>
            <UCard :ui="{ body: 'p-4' }">
              <p class="text-xs text-muted">
                Sold
              </p>
              <USkeleton
                v-if="pending"
                class="h-7 w-16 mt-1"
              />
              <p
                v-else
                class="text-xl font-bold text-muted mt-1"
              >
                {{ data.items_sold }}
              </p>
            </UCard>
          </div>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>
