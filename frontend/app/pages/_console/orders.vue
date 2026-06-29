<script setup lang="ts">
definePageMeta({ layout: 'dashboard', middleware: 'admin-auth' })
useSeoMeta({ title: 'Orders · Admin', robots: 'noindex, nofollow' })
</script>

<template>
  <UDashboardPanel id="admin-orders">
    <template #header>
      <UDashboardNavbar
        title="Orders"
        icon="i-lucide-package"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <AdminOrders />
    </template>
  </UDashboardPanel>
</template>
