<script setup lang="ts">
import type { NavigationMenuItem } from '@nuxt/ui'

const { call } = useAdminApi()
const toast = useToast()

const links: NavigationMenuItem[][] = [[
  { label: 'Dashboard', icon: 'i-lucide-layout-dashboard', to: '/_console', exact: true },
  { label: 'Users', icon: 'i-lucide-users', to: '/_console/users' },
  { label: 'Items', icon: 'i-lucide-tag', to: '/_console/items' },
  { label: 'Orders', icon: 'i-lucide-package', to: '/_console/orders' },
  { label: 'Chats', icon: 'i-lucide-messages-square', to: '/_console/chats' }
]]

async function logout() {
  try {
    await call('/auth/logout', { method: 'POST' })
  } catch {
    // clear locally regardless
  }
  toast.add({ title: 'Signed out', color: 'success' })
  await navigateTo('/_console/login')
}
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar
      id="admin"
      collapsible
      resizable
      :ui="{ footer: 'border-t border-default' }"
    >
      <template #header="{ collapsed }">
        <div
          class="flex items-center gap-2"
          :class="collapsed ? 'justify-center w-full' : 'px-2.5'"
        >
          <UIcon
            name="i-lucide-shield-check"
            class="size-5 text-primary shrink-0"
          />
          <span
            v-if="!collapsed"
            class="font-semibold text-highlighted"
          >Admin Console</span>
        </div>
      </template>

      <template #default="{ collapsed }">
        <UNavigationMenu
          :items="links"
          :collapsed="collapsed"
          orientation="vertical"
          tooltip
        />
      </template>

      <template #footer="{ collapsed }">
        <UButton
          :label="collapsed ? undefined : 'Logout'"
          icon="i-lucide-log-out"
          color="neutral"
          variant="ghost"
          block
          :square="collapsed"
          @click="logout"
        />
      </template>
    </UDashboardSidebar>

    <slot />
  </UDashboardGroup>
</template>
