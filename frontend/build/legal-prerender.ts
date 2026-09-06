import { PRIVACY_POLICY, TERMS_OF_SERVICE, renderLegalDocument, type LegalDocument } from '../app/utils/legal'

/**
 * Injects the legal text into prerendered HTML.
 *
 * Nego-lah builds with `ssr: false`, so Nitro prerenders an EMPTY `#__nuxt`
 * shell for every route. Anything that does not run JavaScript — Google's OAuth
 * verification reviewer included — therefore read a blank page at
 * https://negolah.my/privacy, which is why verification came back saying the
 * privacy policy "does not have sufficient content".
 *
 * Vue's `mount()` empties the container before its first render (it is mounting,
 * not hydrating), so the injected markup vanishes the instant the SPA boots:
 * people get the normal app, crawlers get the full policy.
 *
 * Kept out of nuxt.config, like `pwa/runtime-caching.ts`, so the anchor regex is
 * exercised by real tests instead of being trusted to keep matching.
 */
export const PRERENDERED_LEGAL: Record<string, LegalDocument> = {
  '/privacy': PRIVACY_POLICY,
  '/terms': TERMS_OF_SERVICE
}

/** The empty container Nuxt writes in SPA mode, whatever attributes it carries. */
const EMPTY_SHELL = /<div id="__nuxt"([^>]*)><\/div>/

export class LegalPrerenderError extends Error {}

/**
 * Returns `contents` with the document for `route` inlined, or `null` when the
 * route is not a legal page and should be left alone.
 *
 * Throws when a legal route no longer contains the empty shell: failing the
 * build is the point, because a silent miss ships the blank page all over again.
 */
export function injectLegalDocument(route: string, contents: string): string | null {
  const doc = PRERENDERED_LEGAL[route.replace(/\/+$/, '') || '/']
  if (!doc) return null

  if (!EMPTY_SHELL.test(contents)) {
    throw new LegalPrerenderError(
      `No empty #__nuxt shell found in the prerendered ${route}. The injection anchor changed, `
      + 'so the page would ship without its text — see build/legal-prerender.ts.'
    )
  }

  return contents.replace(
    EMPTY_SHELL,
    (_match, attrs: string) => `<div id="__nuxt"${attrs}>${renderLegalDocument(doc)}</div>`
  )
}
