<script setup lang="ts">
import { TERMS_OF_SERVICE, renderLegalDocument } from '~/utils/legal'

useSeoMeta({
  title: TERMS_OF_SERVICE.title,
  description: TERMS_OF_SERVICE.description
})

const html = renderLegalDocument(TERMS_OF_SERVICE)
</script>

<template>
  <!-- See the note in privacy.vue: build-time constant, shared with the
       prerendered output. -->
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div v-html="html" />
</template>
