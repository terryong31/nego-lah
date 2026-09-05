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

    // Must protect backend API routes and console from navigation fallback
    expect(nuxtConfig).toContain('navigateFallbackDenylist:')
  })
})
