/**
 * Workbox `navigateFallbackDenylist` patterns (SPEC-038).
 *
 * Extracted out of `nuxt.config.ts` so the patterns can be unit-tested against
 * real URLs — see `tests/pwa-navigate-fallback-denylist.test.ts`. The bug this
 * guards against: `navigateFallback: '/'` intercepts every browser
 * *navigation*-mode request (typing a URL, following a link) that isn't
 * denylisted and serves the cached SPA shell instead. Static files like
 * `/robots.txt` were never in the denylist, so once a visitor's browser had
 * installed the service worker, a direct navigation to `/robots.txt` served
 * `index.html` and Vue Router rendered its own 404 page for a route it never
 * defined — a hard refresh bypasses the service worker (Chrome/Firefox both
 * do this for a force-reload navigation) and hits the real static file, which
 * is why the bug looked like it "fixed itself" on reload.
 *
 * Matches any request whose last path segment contains a `.` — i.e. an actual
 * static file — so newly added top-level assets (sitemap.xml, well-known
 * files, etc.) are covered without another denylist edit.
 */
export const navigateFallbackDenylist: RegExp[] = [
  /^\/api\//,
  /^\/_console/,
  /\/[^/?]+\.[^/?]+(?:\?.*)?$/
]
