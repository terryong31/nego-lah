import { describe, expect, it } from 'vitest'
import { navigateFallbackDenylist } from '../pwa/navigate-fallback-denylist'

/**
 * SPEC-038 — the service worker's SPA-shell navigation fallback must never
 * intercept requests for real static files.
 *
 * Reproduces the reported bug: visiting https://negolah.my/robots.txt showed
 * the app's own 404 page (the SPA shell, because Vue Router has no route for
 * it) instead of the plain-text file — only a hard refresh (which bypasses
 * the service worker for that navigation) served the real file.
 */

function isDenylisted(path: string) {
  return navigateFallbackDenylist.some(rule => rule.test(path))
}

describe('SPEC-038 — Workbox navigateFallbackDenylist', () => {
  it('excludes robots.txt from the SPA shell fallback', () => {
    expect(isDenylisted('/robots.txt')).toBe(true)
  })

  it('excludes other top-level static files from the SPA shell fallback', () => {
    for (const path of ['/site.webmanifest', '/sitemap.xml', '/favicon.ico', '/manifest.webmanifest']) {
      expect(isDenylisted(path), path).toBe(true)
    }
  })

  it('still excludes backend API and console routes', () => {
    expect(isDenylisted('/api/negotiations/123')).toBe(true)
    expect(isDenylisted('/_console')).toBe(true)
    expect(isDenylisted('/_console/login')).toBe(true)
  })

  it('does not denylist real SPA routes, so deep links still resolve to the app shell', () => {
    for (const path of ['/', '/items', '/items/abc-123', '/chat', '/login', '/privacy']) {
      expect(isDenylisted(path), path).toBe(false)
    }
  })
})
