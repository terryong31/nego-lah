<script setup lang="ts">
import { PRIVACY_POLICY, renderLegalDocument } from '~/utils/legal'

useSeoMeta({
  title: PRIVACY_POLICY.title,
  description: PRIVACY_POLICY.description
})

// The policy is a build-time constant from app/utils/legal.ts, never user
// input, and it is rendered from the same string that nuxt.config injects
// into the prerendered HTML so the two can never drift apart.
const html = renderLegalDocument(PRIVACY_POLICY)
</script>

<template>
  <div v-html="html" />
</template>
