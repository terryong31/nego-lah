# 8. Build-Time Content Injection for Crawler-Readable Legal Pages

- Status: Accepted
- Date: 2026-09-06
- Deciders: Terry (owner), AI Agent

## Context

ADR-0004 set `ssr: false` and deploys `.output/public` to Cloudflare Pages. That
is the right trade for an authenticated marketplace, but it means every route
except the prerendered `/` is served as an empty app shell. Content only exists
after the browser executes JavaScript.

That became a blocking business problem rather than an SEO nicety: Google's OAuth
verification fetched `https://negolah.my/privacy`, read 18 characters of visible
text ("Nego-Lah Nego-Lah"), and rejected the app with "your privacy policy page
does not have sufficient content". Without verification, the Google sign-in
consent screen stays restricted.

### Decision Drivers

- **Verification is a hard gate.** The reviewer reads raw HTML, not a rendered page.
- **Preserve the SPA.** ADR-0004's zero-server-memory static deploy must survive.
- **No divergent copies.** A separate static privacy page would let the version
  users read drift from the version Google reviews — worse than the bug.
- **Fail loudly.** A mechanism that silently stops working reintroduces a defect
  that only an external reviewer would notice, months later.

### Options Considered

1. **Per-route `ssr: true` in `routeRules`.** Tried and measured: it does not
   work. A global `ssr: false` build produces no server renderer, so Nitro still
   prerenders an empty shell. The route rule only changes which files are written.
2. **Flip the app to `ssr: true`, exempting app routes with `ssr: false`.** The
   documented Nuxt approach, but it breaks the static Cloudflare Pages deploy
   (non-prerendered routes would need a running server) and reverses ADR-0004.
3. **Hand-written static HTML in `public/`.** Works for crawlers, but forks the
   text into two files that will drift, and drops visitors out of the app shell.
4. **Inject the text into the prerendered HTML at build time.** Chosen.

## Decision

Legal content lives once, in `frontend/app/utils/legal.ts`, as markup plus a
`renderLegalDocument()` renderer.

- `pages/privacy.vue` and `pages/terms.vue` render that string, so the in-app
  experience is unchanged.
- `routeRules` marks `/privacy` and `/terms` `prerender: true`, so Cloudflare
  Pages serves a real file per route instead of the SPA fallback.
- `frontend/build/legal-prerender.ts` exports `injectLegalDocument()`, invoked
  from the `prerender:generate` Nitro hook in `nuxt.config.ts`. It swaps the
  empty `<div id="__nuxt"></div>` for the rendered document.

The injected markup is discarded at runtime: Vue's `mount()` clears its container
before the first render because it is mounting, not hydrating. The
`#__nuxt-loader` overlay (`position: fixed; z-index: 999999`) covers the page
until then, so there is no flash of duplicated content.

`injectLegalDocument()` throws `LegalPrerenderError` when the `#__nuxt` anchor
stops matching, failing the build rather than shipping a blank policy again. It
lives outside `nuxt.config.ts` — the same reasoning as `pwa/runtime-caching.ts`
in ADR/SPEC-030 — so the anchor is exercised by unit tests against real shell
markup.

## Consequences

**Positive**

- `/privacy` serves 11,279 characters of visible text with JavaScript disabled,
  up from 18. The same applies to `/terms`.
- One source of truth; the reviewer and the user read identical bytes.
- ADR-0004 stands unchanged — still `ssr: false`, still a static Pages deploy.
- The pattern extends to any future crawler-facing static route.

**Negative**

- The content is markup in a `.ts` file rather than a Vue template, so it is
  rendered with `v-html` and loses component-level niceties (internal links are
  plain anchors, causing a full page load rather than client-side navigation).
  Acceptable for two static legal pages; not a pattern to spread to app UI.
- The injection depends on Nuxt's SPA shell markup. That coupling is deliberate
  and guarded by a build-failing assertion plus tests.

## Related

- ADR-0004 (SPA on Cloudflare Pages) — the constraint this works within.
- SPEC-033 — the implementation and its acceptance criteria.
