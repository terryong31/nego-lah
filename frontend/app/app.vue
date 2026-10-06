<script setup lang="ts">
import { en, ms, zh_cn } from '@nuxt/ui/locale'

const { t } = useI18n()
const { locale, initLanguage } = useLanguage()
const { user } = useAuth()

const uiLocaleMap = {
  en,
  ms,
  zh: zh_cn
}

const uiLocale = computed(() => uiLocaleMap[locale.value] || en)

onMounted(() => {
  initLanguage()
})

watch(user, () => {
  initLanguage()
})

const socialTitle = 'Nego-Lah · Autonomous AI Price Negotiation Marketplace'

// Every route is its own canonical (audit SEO-1). A single global
// `canonical: https://negolah.my` told crawlers every listing duplicated the
// homepage. Path only: query strings are filters and redirects, not pages.
const route = useRoute()
const canonicalUrl = computed(() => `https://negolah.my${route.path === '/' ? '' : route.path}`)
const description = computed(() => t('common.tagline'))

useHead({
  htmlAttrs: {
    lang: computed(() => locale.value)
  },
  // Pages set a bare title ('Chats'); the brand is appended here. The home page
  // sets none and falls back to the app default, which is already the brand.
  titleTemplate: title => (!title || title === 'Nego-Lah' ? 'Nego-Lah' : `${title} · Nego-Lah`),
  link: [{ rel: 'canonical', href: canonicalUrl }]
})

useSeoMeta({
  description,
  ogTitle: socialTitle,
  ogDescription: description,
  ogSiteName: 'Nego-Lah',
  ogUrl: canonicalUrl,
  ogImage: 'https://negolah.my/og-image.png',
  ogImageWidth: 1200,
  ogImageHeight: 675,
  ogImageAlt: 'Nego-Lah - Autonomous AI Price Negotiation Marketplace',
  twitterCard: 'summary_large_image',
  twitterTitle: socialTitle,
  twitterDescription: description,
  twitterImage: 'https://negolah.my/og-image.png',
  twitterImageAlt: 'Nego-Lah - Autonomous AI Price Negotiation Marketplace'
})
</script>

<template>
  <UApp :locale="uiLocale">
    <NuxtPwaManifest />
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
    <!--
      Mounted here rather than in a layout: the tour crosses from `default`
      to `chat` mid-run, and a layout-scoped instance would unmount under it.
    -->
    <TourAppTour />
  </UApp>
</template>
