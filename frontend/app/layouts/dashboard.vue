<script setup lang="ts">
import type { NavigationMenuItem, DropdownMenuItem } from '@nuxt/ui'

const { call } = useAdminApi()
const toast = useToast()
const { t } = useI18n()
const { locale, setAppLanguage } = useLanguage()
const colorMode = useColorMode()

const links = computed<NavigationMenuItem[][]>(() => [[
  { label: t('admin.dashboard'), icon: 'i-lucide-layout-dashboard', to: '/_console', exact: true },
  { label: t('admin.users'), icon: 'i-lucide-users', to: '/_console/users' },
  { label: t('admin.items'), icon: 'i-lucide-tag', to: '/_console/items' },
  { label: t('admin.orders'), icon: 'i-lucide-package', to: '/_console/orders' },
  { label: t('admin.chats'), icon: 'i-lucide-messages-square', to: '/_console/chats' }
]])

async function logout() {
  try {
    await call('/auth/logout', { method: 'POST' })
  } catch {
    // clear locally regardless
  }
  toast.add({ title: t('header.signedOut'), color: 'success' })
  await navigateTo('/_console/login')
}

const footerDropdownItems = computed<DropdownMenuItem[][]>(() => [
  [
    {
      label: t('profile.languagePreference') || 'Language',
      icon: 'i-lucide-languages',
      children: [
        {
          label: 'English',
          icon: locale.value === 'en' ? 'i-lucide-check' : undefined,
          onSelect: () => setAppLanguage('en')
        },
        {
          label: 'Bahasa Melayu',
          icon: locale.value === 'ms' ? 'i-lucide-check' : undefined,
          onSelect: () => setAppLanguage('ms')
        },
        {
          label: '简体中文',
          icon: locale.value === 'zh' ? 'i-lucide-check' : undefined,
          onSelect: () => setAppLanguage('zh')
        }
      ]
    },
    {
      label: 'Theme',
      icon: colorMode.value === 'dark' ? 'i-lucide-moon' : 'i-lucide-sun',
      children: [
        {
          label: 'Light',
          icon: 'i-lucide-sun',
          onSelect: () => { colorMode.preference = 'light' }
        },
        {
          label: 'Dark',
          icon: 'i-lucide-moon',
          onSelect: () => { colorMode.preference = 'dark' }
        },
        {
          label: 'System',
          icon: 'i-lucide-monitor',
          onSelect: () => { colorMode.preference = 'system' }
        }
      ]
    }
  ],
  [
    {
      label: 'Logout',
      icon: 'i-lucide-log-out',
      color: 'error' as const,
      onSelect: logout
    }
  ]
])

const searchGroups = computed(() => [
  {
    id: 'navigation',
    label: 'Navigation',
    items: [
      { label: t('admin.dashboard'), icon: 'i-lucide-layout-dashboard', to: '/_console' },
      { label: t('admin.users'), icon: 'i-lucide-users', to: '/_console/users' },
      { label: t('admin.items'), icon: 'i-lucide-tag', to: '/_console/items' },
      { label: t('admin.orders'), icon: 'i-lucide-package', to: '/_console/orders' },
      { label: t('admin.chats'), icon: 'i-lucide-messages-square', to: '/_console/chats' }
    ]
  }
])

defineExpose({
  logout,
  footerDropdownItems,
  searchGroups
})
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar
      id="admin"
      collapsible
      resizable
      :min-size="14 "
      :ui="{ footer: 'border-t border-default' }"
    >
      <template #header="{ collapsed }">
        <div
          class="flex items-center gap-2"
          :class="collapsed ? 'justify-center w-full' : 'px-2.5'"
        >
          <UIcon
            name="i-lucide-shield-check"
            class="size-5 text-primary shrink-0"
          />
          <span
            v-if="!collapsed"
            class="font-semibold text-highlighted"
          >{{ $t('admin.consoleTitle') }}</span>
        </div>
      </template>

      <template #default="{ collapsed }">
        <UNavigationMenu
          :items="links"
          :collapsed="collapsed"
          orientation="vertical"
          tooltip
        />
      </template>

      <template #footer="{ collapsed }">
        <UDropdownMenu
          :items="footerDropdownItems"
          :content="{ side: 'top', align: 'start' }"
          :ui="{ content: 'w-60' }"
          class="w-full"
        >
          <UButton
            color="neutral"
            variant="ghost"
            :square="collapsed"
            :aria-label="$t('admin.consoleTitle')"
            icon="i-lucide-settings"
            :label="collapsed ? undefined : 'Settings'"
            :trailing-icon="collapsed ? undefined : 'i-lucide-chevrons-up-down'"
            :ui="{ trailingIcon: 'ms-auto' }"
            class="w-full"
          />
        </UDropdownMenu>
      </template>
    </UDashboardSidebar>

    <slot />

    <UDashboardSearch :groups="searchGroups" />
  </UDashboardGroup>
</template>
