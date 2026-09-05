import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useLanguage } from '../../app/composables/useLanguage'

const mockLocale = ref('en')
const mockSetLocale = vi.fn((l: string) => {
  mockLocale.value = l
  return Promise.resolve()
})

vi.mock('vue-i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-i18n')>()
  return {
    ...actual,
    useI18n: () => ({
      locale: mockLocale,
      setLocale: mockSetLocale,
      locales: ref([
        { code: 'en', name: 'English' },
        { code: 'ms', name: 'Bahasa Melayu' },
        { code: 'zh', name: '简体中文' }
      ])
    })
  }
})

vi.mock('#imports', () => ({
  useI18n: () => ({
    locale: mockLocale,
    setLocale: mockSetLocale,
    locales: ref([
      { code: 'en', name: 'English' },
      { code: 'ms', name: 'Bahasa Melayu' },
      { code: 'zh', name: '简体中文' }
    ])
  }),
  useNuxtApp: () => ({
    $i18n: {
      locale: mockLocale,
      setLocale: mockSetLocale,
      locales: ref([
        { code: 'en', name: 'English' },
        { code: 'ms', name: 'Bahasa Melayu' },
        { code: 'zh', name: '简体中文' }
      ])
    }
  }),
  useSupabaseUser: () => ref(null),
  useApi: () => ({
    call: vi.fn().mockResolvedValue({ success: true })
  })
}))

describe('useLanguage composable', () => {
  beforeEach(() => {
    localStorage.clear()
    mockLocale.value = 'en'
    vi.clearAllMocks()
  })

  it('detects browser language based on navigator.language', () => {
    const { detectBrowserLanguage } = useLanguage()

    vi.stubGlobal('navigator', { language: 'zh-CN', languages: ['zh-CN', 'zh'] })
    expect(detectBrowserLanguage()).toBe('zh')

    vi.stubGlobal('navigator', { language: 'ms-MY', languages: ['ms-MY', 'ms'] })
    expect(detectBrowserLanguage()).toBe('ms')

    vi.stubGlobal('navigator', { language: 'en-GB', languages: ['en-GB', 'en'] })
    expect(detectBrowserLanguage()).toBe('en')

    vi.stubGlobal('navigator', { language: 'fr-FR', languages: ['fr-FR'] })
    expect(detectBrowserLanguage()).toBe('en')
  })

  it('sets application language and saves to localStorage', async () => {
    const { setAppLanguage } = useLanguage()
    await setAppLanguage('ms', false)
    expect(mockSetLocale).toHaveBeenCalledWith('ms')
    expect(localStorage.getItem('nego-lah-locale')).toBe('ms')
  })

  it('initializes from localStorage if present for unauthenticated user', async () => {
    localStorage.setItem('nego-lah-locale', 'zh')
    const { initLanguage } = useLanguage()
    await initLanguage()
    expect(mockSetLocale).toHaveBeenCalledWith('zh')
  })

  it('initializes from browser detection if localStorage is empty', async () => {
    vi.stubGlobal('navigator', { language: 'ms-MY', languages: ['ms'] })
    const { initLanguage } = useLanguage()
    await initLanguage()
    expect(mockSetLocale).toHaveBeenCalledWith('ms')
    expect(localStorage.getItem('nego-lah-locale')).toBe('ms')
  })
})
