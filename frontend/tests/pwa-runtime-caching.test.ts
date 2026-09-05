import { describe, expect, it } from 'vitest'
import { MEDIA_EXTENSIONS, runtimeCaching } from '../pwa/runtime-caching'

/**
 * SPEC-030 — the service worker must never intercept media.
 *
 * These assertions run the real Workbox `urlPattern` regexes rather than
 * grepping nuxt.config text, because the bug being guarded against was a
 * pattern that matched more URLs than intended.
 */

const CDN_ORIGIN = 'https://umtsegjkgpfefjvhyysh.supabase.co'
const STORAGE_PREFIX = `${CDN_ORIGIN}/storage/v1/object/public/images`
const APP_ORIGIN = 'https://negolah.my'

function matchingRules(url: string) {
  return runtimeCaching.filter(rule => rule.urlPattern.test(url))
}

/** Workbox registers routes in order and the first match wins. */
function resolveRule(url: string) {
  return matchingRules(url)[0]
}

describe('SPEC-030 — Workbox runtime caching rules', () => {
  it('does not route the Supabase-hosted product demo video through the service worker', () => {
    const videoUrl = `${STORAGE_PREFIX}/videos/negotiation-demo.mp4`

    expect(matchingRules(videoUrl)).toEqual([])
  })

  it('does not route any media extension through the service worker, on any origin', () => {
    for (const ext of MEDIA_EXTENSIONS) {
      expect(matchingRules(`${STORAGE_PREFIX}/videos/demo.${ext}`), `CDN .${ext}`).toEqual([])
      expect(matchingRules(`${APP_ORIGIN}/videos/demo.${ext}`), `app origin .${ext}`).toEqual([])
    }
  })

  it('still caches public storage images under the supabase-storage-images cache', () => {
    for (const path of ['branding/logo.png', 'listings/item-1.webp', 'branding/mark.svg']) {
      const rule = resolveRule(`${STORAGE_PREFIX}/${path}`)
      expect(rule, path).toBeDefined()
      expect(rule!.handler).toBe('StaleWhileRevalidate')
    }

    // The dedicated storage cache must still be reachable for a storage-only
    // format that the generic image rule does not claim first.
    const storageRule = runtimeCaching.find(
      rule => rule.options?.cacheName === 'supabase-storage-images'
    )
    expect(storageRule).toBeDefined()
    expect(storageRule!.urlPattern.test(`${STORAGE_PREFIX}/branding/logo.png`)).toBe(true)
    expect(storageRule!.urlPattern.test(`${STORAGE_PREFIX}/videos/negotiation-demo.mp4`)).toBe(false)
  })

  it('keeps API traffic on NetworkOnly so negotiation responses are never stale', () => {
    const rule = resolveRule('https://api.negolah.my/api/negotiations/123')
    expect(rule).toBeDefined()
    expect(rule!.handler).toBe('NetworkOnly')
  })

  it('still caches Google Fonts with CacheFirst', () => {
    const rule = resolveRule('https://fonts.gstatic.com/s/inter/v13/font.woff2')
    expect(rule).toBeDefined()
    expect(rule!.handler).toBe('CacheFirst')
  })
})
