/* eslint-disable @typescript-eslint/no-explicit-any */
export type SupportedLocale = 'en' | 'ms' | 'zh'

export interface LocaleOption {
  code: SupportedLocale
  name: string
  flag: string
}

export const SUPPORTED_LOCALES: LocaleOption[] = [
  { code: 'en', name: 'English', flag: '🇬🇧' },
  { code: 'ms', name: 'Bahasa Melayu', flag: '🇲🇾' },
  { code: 'zh', name: '简体中文', flag: '🇨🇳' }
]

export function useLanguage() {
  let i18n: any = null
  try {
    i18n = useI18n()
  } catch {
    try {
      i18n = (useNuxtApp() as any)?.$i18n
    } catch {
      i18n = null
    }
  }

  const fallbackLocale = ref<SupportedLocale>('en')

  const locale = computed({
    get: () => {
      const val = i18n?.locale?.value ?? i18n?.locale ?? fallbackLocale.value
      return (val || 'en') as SupportedLocale
    },
    set: (val: SupportedLocale) => {
      if (i18n?.locale && isRef(i18n.locale)) {
        i18n.locale.value = val
      } else if (i18n && 'locale' in i18n) {
        i18n.locale = val
      } else {
        fallbackLocale.value = val
      }
    }
  })

  const locales = computed(() => i18n?.locales?.value ?? i18n?.locales ?? SUPPORTED_LOCALES)

  async function setLocale(newLocale: SupportedLocale) {
    if (i18n?.setLocale) {
      await i18n.setLocale(newLocale)
    } else {
      locale.value = newLocale
    }
  }

  const user = useSupabaseUser()
  const { call } = useApi()

  function detectBrowserLanguage(): SupportedLocale {
    if (typeof navigator === 'undefined') return 'en'
    const candidates = [
      navigator.language,
      ...(navigator.languages || [])
    ].map(l => (l || '').toLowerCase())

    for (const lang of candidates) {
      if (lang.startsWith('zh')) return 'zh'
      if (lang.startsWith('ms') || lang.startsWith('my')) return 'ms'
    }
    return 'en'
  }

  async function syncLanguageToServer(lang: SupportedLocale) {
    if (!user.value?.id) return
    try {
      await call(`/user/${user.value.id}/language`, {
        method: 'PUT',
        body: { language: lang }
      })
      if (user.value.user_metadata) {
        user.value.user_metadata.preferred_language = lang
      }
    } catch (err) {
      console.warn('Failed to sync preferred language to server:', err)
    }
  }

  async function setAppLanguage(newLang: SupportedLocale, persistServer = true) {
    if (!['en', 'ms', 'zh'].includes(newLang)) return
    await setLocale(newLang)
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('nego-lah-locale', newLang)
    }
    if (persistServer && user.value?.id) {
      await syncLanguageToServer(newLang)
    }
  }

  async function initLanguage() {
    if (typeof window === 'undefined') return

    // Case 1: Authenticated user
    if (user.value) {
      const metaLang = user.value.user_metadata?.preferred_language as SupportedLocale | undefined
      if (metaLang && ['en', 'ms', 'zh'].includes(metaLang)) {
        await setAppLanguage(metaLang, false)
        return
      }

      // Metadata is empty: take from localStorage or detect, then sync to server
      const savedLang = localStorage.getItem('nego-lah-locale') as SupportedLocale | null
      const initialLang = (savedLang && ['en', 'ms', 'zh'].includes(savedLang))
        ? savedLang
        : detectBrowserLanguage()

      await setAppLanguage(initialLang, true)
      return
    }

    // Case 2: Unauthenticated / first-time visitor
    const saved = localStorage.getItem('nego-lah-locale') as SupportedLocale | null
    if (saved && ['en', 'ms', 'zh'].includes(saved)) {
      await setLocale(saved)
    } else {
      const detected = detectBrowserLanguage()
      await setLocale(detected)
      localStorage.setItem('nego-lah-locale', detected)
    }
  }

  return {
    locale,
    locales,
    SUPPORTED_LOCALES,
    setAppLanguage,
    initLanguage,
    detectBrowserLanguage,
    syncLanguageToServer
  }
}
