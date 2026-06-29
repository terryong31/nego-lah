<script setup lang="ts">
</script>

<template>
  <div class="flex flex-col h-screen">
    <AppHeader />

    <UMain class="flex-1 min-h-0 flex flex-col w-full max-w-(--ui-container) mx-auto px-4 sm:px-6 lg:px-8 border-x border-default">
      <slot />
    </UMain>
  </div>
</template>
