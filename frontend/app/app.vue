<script setup lang="ts">
const title = 'Nego-lah'
const description = 'AI powered e-commerce site. From image to sales.'

useSeoMeta({
  title,
  description,
  ogTitle: title,
  ogDescription: description
})
</script>

<template>
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
