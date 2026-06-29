<script setup lang="ts">
const user = useSupabaseUser()
const router = useRouter()

watch(user, (newUser) => {
  if (newUser) {
    router.push('/')
  }
}, { immediate: true })
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[50vh] gap-4">
    <UProgress
      indeterminate
      class="w-64"
    />
    <p class="text-sm text-muted">
      Confirming your session, please wait...
    </p>
  </div>
</template>
