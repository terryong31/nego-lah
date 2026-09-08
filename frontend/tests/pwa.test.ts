import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('PWA & Cloudflare Pages Security Configuration', () => {
  const rootDir = path.resolve(__dirname, '..')
  const headersPath = path.resolve(rootDir, 'public/_headers')
  const nuxtConfigPath = path.resolve(rootDir, 'nuxt.config.ts')

  it('declares public/_headers for Cloudflare Pages with service worker rules', () => {
    expect(fs.existsSync(headersPath)).toBe(true)
    const headersContent = fs.readFileSync(headersPath, 'utf-8')

    // Must define rules for /sw.js
    expect(headersContent).toContain('/sw.js')
    expect(headersContent).toContain('Service-Worker-Allowed: /')
    expect(headersContent).toContain('Cache-Control: no-cache, no-store, must-revalidate')
    expect(headersContent).toContain('Content-Type: application/javascript; charset=utf-8')

    // Must define rules for workbox bundles
    expect(headersContent).toContain('/workbox-*.js')
    expect(headersContent).toContain('Cache-Control: public, max-age=31536000, immutable')

    // Must define rules for webmanifest
    expect(headersContent).toContain('/site.webmanifest')
    expect(headersContent).toContain('Content-Type: application/manifest+json; charset=utf-8')
  })

  it('configures Content-Security-Policy with worker-src and child-src in _headers', () => {
    expect(fs.existsSync(headersPath)).toBe(true)
    const headersContent = fs.readFileSync(headersPath, 'utf-8')

    expect(headersContent).toContain('Content-Security-Policy:')
    expect(headersContent).toContain('worker-src \'self\' blob:')
    expect(headersContent).toContain('child-src \'self\' blob:')
    expect(headersContent).toContain('connect-src \'self\'')
    expect(headersContent).toContain('https://api.negolah.my')
    expect(headersContent).toContain('https://*.supabase.co')
    expect(headersContent).toContain('https://challenges.cloudflare.com')
  })

  it('configures @vite-pwa/nuxt and workbox denylists in nuxt.config.ts', () => {
    const nuxtConfig = fs.readFileSync(nuxtConfigPath, 'utf-8')

    // Module registration
    expect(nuxtConfig).toContain('\'@vite-pwa/nuxt\'')

    // PWA configuration block
    expect(nuxtConfig).toContain('pwa:')
    expect(nuxtConfig).toContain('registerType: \'autoUpdate\'')
    expect(nuxtConfig).toContain('navigateFallback: \'/\'')

    // Must protect backend API routes, console, and static files (SPEC-038)
    // from navigation fallback — the patterns themselves are unit-tested
    // against real URLs in pwa-navigate-fallback-denylist.test.ts.
    expect(nuxtConfig).toContain('navigateFallbackDenylist')
    expect(nuxtConfig).toContain('./pwa/navigate-fallback-denylist')

    // SPEC-030: runtime caching rules live in a shared, unit-tested module
    expect(nuxtConfig).toContain('./pwa/runtime-caching')
    expect(nuxtConfig).toContain('runtimeCaching')
  })

  it('leaves the install prompt to the browser so beforeinstallprompt is never suppressed', () => {
    const nuxtConfig = fs.readFileSync(nuxtConfigPath, 'utf-8')

    // SPEC-030: @vite-pwa/nuxt calls preventDefault() on `beforeinstallprompt`
    // when this is enabled. Nothing in the app calls `$pwa.install()`, so Chrome
    // suppressed its own banner and logged a console warning. Chrome's native
    // install affordance is used instead.
    expect(nuxtConfig).toContain('installPrompt: false')
    expect(nuxtConfig).not.toContain('installPrompt: true')
  })

  it('polls for service worker updates so an SPA session is not pinned to an old worker', () => {
    const nuxtConfig = fs.readFileSync(nuxtConfigPath, 'utf-8')

    // SPEC-030: useRegisterSW only checks for a new worker on a hard navigation,
    // and an ssr:false SPA never makes one. Without this, a long-lived tab keeps
    // running the worker it booted with.
    const match = nuxtConfig.match(/periodicSyncForUpdates:\s*(\d+)/)
    expect(match).not.toBeNull()
    expect(Number(match![1])).toBeGreaterThan(0)
  })

  it('registers the client plugin that purges media cached by the old catch-all rule', () => {
    const pluginPath = path.resolve(rootDir, 'app/plugins/purge-stale-media-cache.client.ts')
    expect(fs.existsSync(pluginPath)).toBe(true)
  })
})
