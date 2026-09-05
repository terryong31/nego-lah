<script setup lang="ts">
definePageMeta({ layout: 'dashboard', middleware: 'admin-auth' })
useSeoMeta({ title: 'Items · Admin', robots: 'noindex, nofollow' })
</script>

<template>
  <UDashboardPanel id="admin-items">
    <template #header>
      <UDashboardNavbar
        title="Items"
        icon="i-lucide-tag"
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
      <AdminItems />
    </template>
  </UDashboardPanel>
</template>
