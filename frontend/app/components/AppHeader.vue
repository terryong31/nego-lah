<script setup lang="ts">
const user = useSupabaseUser()
const supabase = useSupabaseClient()
const router = useRouter()
const route = useRoute()
const toast = useToast()

// Hide the header Login button while on the auth pages
const isAuthPage = computed(() =>
  ['/login', '/register', '/forgot-password', '/reset-password'].includes(route.path)
)

const dropdownItems = computed(() => {
  if (!user.value) return []
  return [
    [
      {
        label: user.value.email || 'My Account',
        disabled: true
      }
    ],
    [
      {
        label: 'Chat',
        icon: 'i-lucide-message-square',
        onSelect: () => router.push('/chat')
      },
      {
        label: 'My Orders',
        icon: 'i-lucide-package',
        onSelect: () => router.push('/orders')
      },
      {
        label: 'Profile Settings',
        icon: 'i-lucide-settings',
        onSelect: () => router.push('/profile')
      }
    ],
    [
      {
        label: 'Sign Out',
        icon: 'i-lucide-log-out',
        onSelect: async () => {
          const { error } = await supabase.auth.signOut()
          if (error) {
            toast.add({ title: 'Logout failed', description: error.message, color: 'error' })
          } else {
            toast.add({ title: 'Signed out', description: 'See you again!', color: 'success' })
            router.push('/')
          }
        }
      }
    ]
  ]
})
</script>

<template>
  <UHeader :ui="{ toggle: 'hidden' }">
    <template #left>
      <NuxtLink
        to="/"
        class="font-bold text-xl tracking-tight text-primary"
      >
        Nego-lah
      </NuxtLink>
    </template>

    <template #right>
      <div class="flex items-center gap-3">
        <ClientOnly>
          <UDropdownMenu
            v-if="user"
            :items="dropdownItems"
          >
            <div class="flex items-center gap-1.5 cursor-pointer">
              <UUser
                :name="`Hello, ${user.user_metadata?.display_name || user.email || 'there'}`"
                :avatar="{
                  src: user.user_metadata?.avatar_url,
                  alt: user.email || '',
                  loading: 'lazy'
                }"
                :ui="{ avatar: 'group-hover/user:scale-100 group-has-focus-visible/user:scale-100' }"
              />
              <UIcon
                name="i-lucide-chevron-down"
                class="size-4 text-muted shrink-0"
              />
            </div>
          </UDropdownMenu>
          <UButton
            v-else-if="!isAuthPage"
            to="/login"
            label="Login"
            variant="solid"
          />

          <template #fallback>
            <USkeleton class="size-8 rounded-full" />
          </template>
        </ClientOnly>
      </div>
    </template>
  </UHeader>
</template>
