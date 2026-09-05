<script setup lang="ts">
import { en, ms, zh_cn } from '@nuxt/ui/locale'
import { useLanguage, type SupportedLocale } from '~/composables/useLanguage'

const { locale, setAppLanguage } = useLanguage()

// Use 'zh-CN' so Nuxt UI's getEmojiFlag parses the country code 'CN' and displays 🇨🇳
const locales = [
  en,
  { ...ms, name: 'Bahasa Melayu' },
  { ...zh_cn, code: 'zh-CN', name: '简体中文' }
]

const selected = computed({
  get: () => {
    if (locale.value === 'zh') return 'zh-CN'
    return (locale.value || 'en') as string
  },
  set: (val: string) => {
    const target = val === 'zh-CN' ? 'zh' : val
    setAppLanguage(target as SupportedLocale)
  }
})
</script>

<template>
  <ULocaleSelect
    v-model="selected"
    :locales="locales"
    color="neutral"
    variant="outline"
    size="md"
    class="w-48"
    :aria-label="$t('common.selectLanguage')"
  />
</template>
