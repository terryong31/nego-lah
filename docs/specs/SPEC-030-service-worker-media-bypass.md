---
id: SPEC-030
title: Service Worker Media Bypass and Native PWA Install Prompt
status: complete
priority: high
created: 2026-09-06
tags: [pwa, service-worker, video, frontend]
assigned: agent
---

# Context & Objectives
The homepage product walkthrough video (`ProductVideoShowcase.vue`) intermittently fails to
render its first frame — the poster stays up and playback never starts. A hard refresh usually
fixes it. The CDN is healthy: Supabase Storage answers `Range` requests with `206 Partial
Content` and `cache-control: max-age=31536000`, and the MP4 is FastStart (SPEC-028).

Root cause is the service worker. The Workbox `runtimeCaching` rule keyed
`supabase-storage-images` uses the pattern `/.*\/storage\/v1\/object\/public\/.*/i`, which
matches **every** public storage object — including `videos/negotiation-demo.mp4`. Because the
generic image rule is registered earlier and already claims image extensions, that rule in
practice matches only the 13.5 MB video. `StaleWhileRevalidate` then calls `response.clone()`
on the streaming media body so it can be cached. The media element stops reading once its
buffer is full, the tee'd clone stalls under backpressure, and playback deadlocks before the
first frame decodes. `cacheableResponse: { statuses: [0, 200] }` rejects the `206` only *after*
the clone, so the cost is paid with no cache benefit. Timing-dependent, hence intermittent.

Separately, `pwa.client.installPrompt: true` makes `@vite-pwa/nuxt` call `preventDefault()` on
`beforeinstallprompt` and stash the event, but no component ever calls `$pwa.install()`. Chrome
suppresses its own banner and logs: *"Banner not shown: beforeinstallpromptevent.preventDefault()
called. The page must call beforeinstallpromptevent.prompt() to show the banner."*

# Acceptance Criteria
- [x] No Workbox `runtimeCaching` route matches audio/video URLs, so media requests are never
      intercepted by the service worker and stream natively with full byte-range support.
- [x] The `supabase-storage-images` route matches only image objects, matching its stated intent.
- [x] Runtime caching rules live in an importable, unit-testable module rather than inline config.
- [x] `ProductVideoShowcase.vue` recovers from a failed media load instead of stranding the poster.
- [x] `pwa.client.installPrompt` is `false`, so Chrome's native install UI is used and the
      `beforeinstallprompt` console warning no longer fires.
- [x] Existing PWA, video showcase, and homepage tests continue to pass.
- [x] A long-lived SPA session picks up a newly deployed service worker without a hard reload.
- [x] Media already cached by the previous catch-all rule is purged from Cache Storage.

# Technical Design & Contracts
### `frontend/pwa/runtime-caching.ts`
Exports `runtimeCaching: RuntimeCaching[]`, consumed by `nuxt.config.ts` as
`pwa.workbox.runtimeCaching`. Also exports `MEDIA_EXTENSIONS` for reuse in tests.

Route order (first match wins in Workbox):
1. Google Fonts — `CacheFirst`.
2. Images (`png|jpg|jpeg|svg|gif|webp|avif`) — `StaleWhileRevalidate`, cache `static-images`.
3. Public Supabase Storage **images only** — `StaleWhileRevalidate`, cache `supabase-storage-images`.
4. `https://api.negolah.my/api/*` — `NetworkOnly`.

Media (`mp4|webm|ogg|mov|m4v|mp3|wav|m4a`) matches **no** route, on any origin. Workbox never
calls `respondWith`, so the browser owns the media stream end to end.

### `ProductVideoShowcase.vue`
Add a bounded recovery path: on the `<video>` `error` event, retry `load()` + play at most
`MAX_LOAD_RETRIES` (2) times with a short backoff. Add a `loadeddata` listener that plays once
data is available, covering the case where the element becomes ready after the initial
intersection check.

### `frontend/nuxt.config.ts`
`pwa.client.installPrompt: false`.

`pwa.periodicSyncForUpdates: 3600` (seconds). `useRegisterSW` only checks for a new service
worker on a hard navigation. This is an SPA (`ssr: false`), so client-side routing produces no
navigations and a tab left open for hours would keep running the old worker — including the old
media route this spec removes. The @vite-pwa plugin's periodic sync re-fetches `sw.js` with
`cache: no-store` and calls `registration.update()`; combined with `registerType: 'autoUpdate'`
plus `skipWaiting`/`clientsClaim`, the replacement activates and claims open clients at once.

### Purging already-cached media
`cleanupOutdatedCaches` only prunes stale *precaches*, so a browser that cached the video under
the old catch-all keeps a dead ~13.5 MB entry in `supabase-storage-images`. Nothing serves it
now that no route matches media, but it holds storage quota until eviction. Rather than
switching the whole build to `injectManifest` for one cleanup, the page purges it directly —
Cache Storage is same-origin accessible from the client. `app/utils/mediaCache.ts` walks every
cache, deletes entries whose pathname has a media extension, and records a one-shot flag in
`localStorage` so it costs nothing on later visits.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** No rule's `urlPattern` matches the Supabase `negotiation-demo.mp4` URL.
- [x] **Scenario 2:** No rule matches any media extension on the app origin or the CDN.
- [x] **Scenario 3:** The `supabase-storage-images` rule still matches a public storage `.webp`/`.png`.
- [x] **Scenario 4:** API routes still resolve to a `NetworkOnly` handler.
- [x] **Scenario 5:** `nuxt.config.ts` sets `installPrompt: false` and imports the shared rules module.
- [x] **Scenario 6:** The video element retries `load()` after an `error` event, capped at 2 retries.
- [x] **Scenario 7:** A `loadeddata` event triggers playback.
- [x] **Scenario 8:** `isCachedMediaUrl` flags media (with query strings) and spares images/scripts.
- [x] **Scenario 9:** `purgeCachedMedia` deletes media across every cache and keeps non-media.
- [x] **Scenario 10:** The purge runs once, then short-circuits on the persisted flag.
- [x] **Scenario 11:** The purge is inert when Cache Storage or `localStorage` is unavailable.
- [x] **Scenario 12:** `nuxt.config.ts` sets a non-zero `periodicSyncForUpdates`.

# Implementation Files
- `frontend/pwa/runtime-caching.ts` - Workbox runtime caching rules, media excluded
- `frontend/nuxt.config.ts` - Consumes the rules module; disables the custom install prompt
- `frontend/app/components/home/ProductVideoShowcase.vue` - Bounded media load recovery
- `frontend/tests/pwa-runtime-caching.test.ts` - Behavioral tests over the real regexes
- `frontend/tests/pwa.test.ts` - Install prompt + module wiring assertions
- `frontend/tests/components/home/ProductVideoShowcase.test.ts` - Recovery scenarios
- `frontend/app/utils/mediaCache.ts` - One-shot Cache Storage media purge
- `frontend/app/plugins/purge-stale-media-cache.client.ts` - Runs the purge when the app is idle
- `frontend/tests/utils/mediaCache.test.ts` - Purge scenarios
