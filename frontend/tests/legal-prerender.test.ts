import { describe, expect, it } from 'vitest'
import { LegalPrerenderError, injectLegalDocument } from '../build/legal-prerender'
import { PRIVACY_POLICY } from '../app/utils/legal'

/**
 * SPEC-033 — the legal pages must be readable without JavaScript.
 *
 * Google's OAuth verification fetched https://negolah.my/privacy, got the empty
 * `ssr: false` app shell, and failed the app for a privacy policy with
 * insufficient content. These assertions run the real injection against the
 * real shell markup, because the failure mode being guarded against is an
 * anchor that silently stops matching.
 */

// The container Nuxt writes in SPA mode, copied from a real prerendered file.
const SHELL = '<!DOCTYPE html><html><head><title>Nego-Lah</title></head>'
  + '<body><div id="__nuxt" class="isolate"></div><div id="__nuxt-loader"></div></body></html>'

function visibleText(html: string): string {
  return html
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('build/legal-prerender', () => {
  it('inlines the policy into the empty shell', () => {
    const out = injectLegalDocument('/privacy', SHELL)

    expect(out).not.toBeNull()
    expect(visibleText(out!)).toContain('Privacy Policy')
    expect(visibleText(out!)).toContain(PRIVACY_POLICY.lastUpdated)
  })

  it('turns a blank page into a substantial one', () => {
    expect(visibleText(SHELL).length).toBeLessThan(50)
    expect(visibleText(injectLegalDocument('/privacy', SHELL)!).length).toBeGreaterThan(5000)
  })

  it('keeps the container id and its attributes so Vue still mounts over it', () => {
    const out = injectLegalDocument('/privacy', SHELL)!

    expect(out).toContain('<div id="__nuxt" class="isolate">')
    expect(out).not.toContain('<div id="__nuxt" class="isolate"></div>')
  })

  it('injects the terms page too', () => {
    expect(visibleText(injectLegalDocument('/terms', SHELL)!)).toContain('Terms of Service')
  })

  it('tolerates a trailing slash, as Cloudflare Pages redirects to one', () => {
    expect(injectLegalDocument('/privacy/', SHELL)).not.toBeNull()
  })

  it('leaves every other route alone', () => {
    expect(injectLegalDocument('/', SHELL)).toBeNull()
    expect(injectLegalDocument('/items', SHELL)).toBeNull()
    expect(injectLegalDocument('/privacy-something-else', SHELL)).toBeNull()
  })

  // Silently skipping would ship the blank page again, which is the whole bug.
  it('fails the build when the shell anchor no longer matches', () => {
    expect(() => injectLegalDocument('/privacy', '<body><div id="app"></div></body>'))
      .toThrow(LegalPrerenderError)
  })
})
