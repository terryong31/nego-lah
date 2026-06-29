<script setup lang="ts">
definePageMeta({ layout: 'dashboard', middleware: 'admin-auth' })
useSeoMeta({ title: 'Users · Admin', robots: 'noindex, nofollow' })
</script>

<template>
  <UDashboardPanel id="admin-users">
    <template #header>
      <UDashboardNavbar
        title="Users"
        icon="i-lucide-users"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <AdminUsers />
    </template>
  </UDashboardPanel>
</template>
