import en from './app/locales/en.json'
import ms from './app/locales/ms.json'
import zh from './app/locales/zh.json'

export default defineI18nConfig(() => ({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en,
    ms,
    zh
  }
}))
