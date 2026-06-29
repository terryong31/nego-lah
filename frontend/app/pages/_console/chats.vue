<script setup lang="ts">
definePageMeta({ layout: 'dashboard', middleware: 'admin-auth' })
useSeoMeta({ title: 'Chats · Admin', robots: 'noindex, nofollow' })
</script>

<template>
  <UDashboardPanel
    id="admin-chats"
    :ui="{ body: 'p-0 sm:p-0 gap-0 overflow-hidden' }"
  >
    <template #header>
      <UDashboardNavbar
        title="Chats"
        icon="i-lucide-messages-square"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <AdminChats />
    </template>
  </UDashboardPanel>
</template>
