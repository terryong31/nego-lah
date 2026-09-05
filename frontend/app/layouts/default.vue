<script setup lang="ts">
const route = useRoute()
// Root page goes edge-to-edge; every other client page gets the framed border.
const showBorder = computed(() => route.path !== '/')
</script>

<template>
  <div class="min-h-screen flex flex-col overflow-x-clip">
    <AppHeader class="shrink-0" />

    <UMain
      :ui="{ base: 'min-h-0' }"
      class="flex-1 py-6 max-w-(--ui-container) w-full mx-auto px-4 sm:px-6 lg:px-8"
      :class="showBorder && 'border-x border-default'"
    >
      <slot />
    </UMain>

    <USeparator class="shrink-0" />

    <UFooter
      class="shrink-0"
      :ui="{ container: 'py-4 lg:py-4' }"
    >
      <template #left>
        <p class="text-sm text-muted">
          © Nego-lah {{ new Date().getFullYear() }} • Developed by <ULink
            to="https://linkedin.com/in/ongkokdonq"
            target="_blank"
            class="underline"
          >Terry Ong</ULink>
        </p>
      </template>
      <div class="flex gap-4">
        <UButton
          to="/privacy"
          :label="$t('footer.privacy')"
          color="neutral"
          variant="link"
        />
        <UButton
          to="/terms"
          :label="$t('footer.terms')"
          color="neutral"
          variant="link"
        />
      </div>
      <template #right>
        <LanguageSelect />
        <UColorModeSelect />
      </template>
    </UFooter>
  </div>
</template>
