<script setup lang="ts">
import { loginRedirect } from '~/utils/auth'

const user = useSupabaseUser()
const supabase = useSupabaseClient()
const router = useRouter()
const route = useRoute()
const toast = useToast()
const { t } = useI18n()
const { hasUnread, clearUnread } = useNotifications()

// Hide the header Login button while on the auth pages
const isAuthPage = computed(() =>
  ['/login', '/register', '/forgot-password', '/reset-password'].includes(route.path)
)

const dropdownItems = computed(() => {
  if (!user.value) return []
  return [
    [
      {
        label: user.value.email || t('header.myAccount'),
        disabled: true
      }
    ],
    [
      {
        label: t('header.chat'),
        icon: 'i-lucide-message-square',
        slot: 'chat',
        onSelect: () => {
          clearUnread()
          router.push('/chat')
        }
      },
      {
        label: t('header.myOrders'),
        icon: 'i-lucide-package',
        onSelect: () => router.push('/orders')
      },
      {
        label: t('header.profileSettings'),
        icon: 'i-lucide-settings',
        onSelect: () => router.push('/profile')
      }
    ],
    [
      {
        label: t('header.signOut'),
        icon: 'i-lucide-log-out',
        onSelect: async () => {
          const { error } = await supabase.auth.signOut()
          if (error) {
            toast.add({ title: t('header.logoutFailed'), description: error.message, color: 'error' })
          } else {
            toast.add({ title: t('header.signedOut'), description: t('header.seeYouAgain'), color: 'success' })
            if (isAuthGuarded(route)) {
              await router.push('/')
            }
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
        class="focus-visible:outline-primary rounded-md inline-flex items-center"
        aria-label="Nego-Lah Home"
      >
        <AppLogo size="md" />
      </NuxtLink>
    </template>

    <template #right>
      <div class="flex items-center gap-3">
        <ClientOnly>
          <template v-if="user">
            <!-- User avatar dropdown menu with unread UChip -->
            <UDropdownMenu
              :modal="false"
              :items="dropdownItems"
              :content="{ align: 'end' }"
              :ui="{ item: 'items-center' }"
            >
              <UChip
                :show="hasUnread"
                color="primary"
                inset
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
              </UChip>

              <!-- Unread badge only; the leading icon stays the themed default -->
              <template #chat-trailing>
                <UChip
                  :show="hasUnread"
                  color="primary"
                  standalone
                  size="xs"
                />
              </template>
            </UDropdownMenu>
          </template>

          <UButton
            v-else-if="!isAuthPage"
            :to="loginRedirect(route.fullPath)"
            :label="$t('header.login')"
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
