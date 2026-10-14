import { describe, expect, it } from 'vitest'
import { MEDIA_EXTENSIONS, runtimeCaching } from '../pwa/runtime-caching'
import { contentSecurityPolicy } from '../build/csp'

/**
 * SPEC-030 — the service worker must never intercept media.
 *
 * These assertions run the real Workbox `urlPattern` regexes rather than
 * grepping nuxt.config text, because the bug being guarded against was a
 * pattern that matched more URLs than intended.
 */

const CDN_ORIGIN = 'https://example-project.supabase.co'
const STORAGE_PREFIX = `${CDN_ORIGIN}/storage/v1/object/public/images`
const APP_ORIGIN = 'https://negolah.my'
// SPEC-045: the demo video moved to a Cloudflare R2 bucket behind this domain.
const MEDIA_CDN_ORIGIN = 'https://media.negolah.my'

/**
 * Matches the way Workbox's `RegExpRoute` does: a same-origin URL may match
 * anywhere, but a cross-origin URL only counts when the match starts at index 0.
 * Testing with plain `regex.test()` let an unanchored pattern look as if it
 * claimed Supabase images, when in the browser it never did.
 */
function workboxMatches(pattern: RegExp, url: string) {
  const match = new RegExp(pattern.source, pattern.flags.replace('g', '')).exec(url)
  if (!match) return false
  return new URL(url).origin === APP_ORIGIN || match.index === 0
}

function matchingRules(url: string) {
  return runtimeCaching.filter(rule => workboxMatches(rule.urlPattern, url))
}

/** Workbox registers routes in order and the first match wins. */
function resolveRule(url: string) {
  return matchingRules(url)[0]
}

describe('SPEC-030 — Workbox runtime caching rules', () => {
  it('does not route the R2-hosted product demo video through the service worker', () => {
    expect(matchingRules(`${MEDIA_CDN_ORIGIN}/videos/negotiation-demo.mp4`)).toEqual([])
    // ...nor the old Supabase location, still guarded so a regression is visible.
    expect(matchingRules(`${STORAGE_PREFIX}/videos/negotiation-demo.mp4`)).toEqual([])
  })

  it('does not route any media extension through the service worker, on any origin', () => {
    for (const ext of MEDIA_EXTENSIONS) {
      expect(matchingRules(`${STORAGE_PREFIX}/videos/demo.${ext}`), `CDN .${ext}`).toEqual([])
      expect(matchingRules(`${APP_ORIGIN}/videos/demo.${ext}`), `app origin .${ext}`).toEqual([])
      expect(matchingRules(`${MEDIA_CDN_ORIGIN}/videos/demo.${ext}`), `media CDN .${ext}`).toEqual([])
    }
  })

  // SPEC-107: Workbox re-issues a claimed request with fetch(), which `connect-src`
  // governs — not `img-src`. Claiming Supabase images blocked every one of them.
  it('leaves public storage images to the browser', () => {
    for (const path of ['items/5e2a/0.jpeg', 'listings/item-1.webp', 'branding/mark.svg?width=400']) {
      expect(matchingRules(`${STORAGE_PREFIX}/${path}`), path).toEqual([])
    }
  })

  it('claims no cross-origin URL that connect-src forbids the worker to fetch', () => {
    const connectSrc = contentSecurityPolicy({ dev: false })
      .split(';')
      .find(directive => directive.trim().startsWith('connect-src'))!
      .trim()
      .split(/\s+/)
      .slice(1)
    const allowed = (origin: string) => connectSrc.some((source) => {
      if (!source.startsWith('https://')) return false
      const host = new URL(origin).host
      const pattern = source.slice('https://'.length)
      return pattern.startsWith('*.') ? host.endsWith(pattern.slice(1)) : host === pattern
    })

    for (const url of [
      `${STORAGE_PREFIX}/items/5e2a/0.jpeg`,
      `${STORAGE_PREFIX}/branding/logo.png`,
      'https://fonts.googleapis.com/css2?family=Inter',
      'https://fonts.gstatic.com/s/inter/v13/font.woff2',
      `${MEDIA_CDN_ORIGIN}/posters/demo.webp`,
      'https://images.example.com/photo.jpg'
    ]) {
      if (matchingRules(url).length === 0) continue
      expect(allowed(new URL(url).origin), url).toBe(true)
    }
  })

  it('still caches same-origin images', () => {
    const rule = resolveRule(`${APP_ORIGIN}/images/hero.webp`)
    expect(rule).toBeDefined()
    expect(rule!.handler).toBe('StaleWhileRevalidate')
  })

  // SPEC-104 SEC-04: an unmatched request is never handled by the worker, so the
  // browser fetches it natively and nothing is cached. That is the protection —
  // the old `/api/` NetworkOnly rule matched no real route and only looked like one.
  it('leaves every API request to the browser, image-like paths included', () => {
    for (const url of [
      'https://api.negolah.my/chat/stream',
      'https://api.negolah.my/user/u-1/profile',
      'https://api.negolah.my/payment/checkout',
      'https://api.negolah.my/admin/items/export.png',
      'https://api.negolah.my/items/1/photo.webp?width=400',
      'http://localhost:8000/items/1/photo.png'
    ]) {
      expect(matchingRules(url), url).toEqual([])
    }
  })

  it('has no rule that matches only invented URLs', () => {
    expect(runtimeCaching.some(rule => rule.urlPattern.source.includes('\\/api\\/'))).toBe(false)
  })
})
