<script setup lang="ts">
const route = useRoute()
// Root page goes edge-to-edge; every other client page gets the framed border.
const showBorder = computed(() => route.path !== '/')
</script>

<template>
  <div>
    <AppHeader />

    <UMain
      class="min-h-[80vh] py-6 max-w-(--ui-container) mx-auto px-4 sm:px-6 lg:px-8"
      :class="showBorder && 'border-x border-default'"
    >
      <slot />
    </UMain>

    <USeparator />

    <UFooter>
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
          label="Privacy"
          color="neutral"
          variant="link"
        />
        <UButton
          to="/terms"
          label="Terms"
          color="neutral"
          variant="link"
        />
      </div>
      <template #right>
        <UButton
          to="https://github.com/terryong31/nego-lah"
          target="_blank"
          icon="i-simple-icons-github"
          aria-label="GitHub"
          color="neutral"
          variant="link"
          size="xl"
        />
        <UColorModeSelect />
      </template>
    </UFooter>
  </div>
</template>
