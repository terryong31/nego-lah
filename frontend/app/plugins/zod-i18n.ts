/* eslint-disable @typescript-eslint/no-explicit-any */
import { z } from 'zod'
import en from '~/locales/en.json'
import ms from '~/locales/ms.json'
import zh from '~/locales/zh.json'

const DICTIONARIES = {
  en,
  ms,
  zh
}

let currentLocale: 'en' | 'ms' | 'zh' = 'en'

export function setupZodI18n(locale: 'en' | 'ms' | 'zh' = 'en') {
  currentLocale = locale

  z.setErrorMap(((issue: any, ctx: any) => {
    const dict = DICTIONARIES[currentLocale] || DICTIONARIES.en
    const v = dict.validation

    // 1. Email format error
    if (issue.code === 'invalid_format' || (issue as any).format === 'email') {
      return { message: v.emailInvalid }
    }

    // 2. Minimum length / value constraint
    if (issue.code === 'too_small') {
      const min = (issue as any).minimum
      const origin = (issue as any).origin || (issue as any).type
      if (origin === 'string' || typeof min === 'number') {
        if (min === 8) {
          return { message: v.passwordMin.replace('{min}', String(min)) }
        }
        return { message: v.stringMin.replace('{min}', String(min)) }
      }
      if (origin === 'number') {
        return { message: v.pricePositive }
      }
    }

    // 3. Maximum length / value constraint
    if (issue.code === 'too_big') {
      const max = (issue as any).maximum
      return { message: v.stringMax.replace('{max}', String(max)) }
    }

    // 4. Missing required field / invalid type
    if (issue.code === 'invalid_type') {
      if ((issue as any).received === 'undefined' || (issue as any).received === 'null') {
        return { message: v.required }
      }
      return { message: v.numberInvalid || 'Invalid value' }
    }

    // 5. Custom error or refinement
    const customCode = (issue as any).params?.code || issue.message
    if (customCode && (v as any)[customCode]) {
      return { message: (v as any)[customCode] }
    }
    if (issue.message === 'Passwords don\'t match') {
      return { message: v.passwordsMismatch }
    }
    if (issue.message === 'Minimum price cannot exceed the listing price') {
      return { message: v.minPriceMax }
    }
    if (issue.message && String(issue.message).includes('Malaysian phone')) {
      return { message: v.phoneInvalid }
    }
    if (issue.code === 'custom' && issue.message) {
      return { message: issue.message }
    }

    return { message: ctx?.defaultError || 'Invalid input' }
  }) as any)
}

export function formatZodIssue(issue: z.ZodIssue, locale: 'en' | 'ms' | 'zh' = currentLocale): string {
  const dict = DICTIONARIES[locale] || DICTIONARIES.en
  const v = dict.validation
  const customCode = (issue as any).params?.code || issue.message
  if (customCode && (v as any)[customCode]) {
    return (v as any)[customCode]
  }
  return issue.message
}

export function formatZodError(error: z.ZodError, locale: 'en' | 'ms' | 'zh' = currentLocale): string[] {
  return error.issues.map(i => formatZodIssue(i, locale))
}

export default defineNuxtPlugin((nuxtApp) => {
  const i18n = (nuxtApp as any).$i18n
  const initial = (i18n?.locale?.value || i18n?.locale || 'en') as 'en' | 'ms' | 'zh'
  setupZodI18n(initial)

  if (i18n?.locale && isRef(i18n.locale)) {
    watch(i18n.locale, (newLoc: any) => {
      setupZodI18n((newLoc || 'en') as 'en' | 'ms' | 'zh')
    })
  }
})
