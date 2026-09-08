---
id: SPEC-045
title: Cloudflare R2 Media CDN for the Demo Video
status: in-progress
priority: high
created: 2026-09-08
tags: [frontend, infra, cdn, storage, performance]
assigned: agent
---

# Context & Objectives

The homepage product-walkthrough video (`ProductVideoShowcase.vue`) is a 12.9 MB
FastStart MP4 served from the Supabase Storage public `images` bucket (SPEC-028).
The `<video>` element is `autoplay preload="auto"`, so **every** homepage visit
fetches the whole file regardless of whether the visitor ever scrolls to the
`#how-it-works` section. ~480 loads exhausted the Supabase Free plan's 5 GB
cached-egress quota in one billing cycle (dashboard showed 6.2 GB / 124%), which
throttles the whole project.

Supabase Storage is the wrong home for a large static marketing asset on a metered
free plan. Cloudflare R2 has **zero egress fees**, is fronted by the same edge CDN
as the Pages deployment, and supports HTTP range streaming. The video is also
oversized: 1584×1080 @ 50 fps with an audio track it never plays.

Objectives:
1. Serve the demo video from Cloudflare R2 via the custom domain `media.negolah.my`.
2. Re-encode it to ~2 MB (720p30, no audio, H.264 + FastStart).
3. Only download it when the section scrolls into view.
4. Remove the binary from the git repo.

# Acceptance Criteria

- [ ] `ProductVideoShowcase.vue` resolves its video URL from
      `runtimeConfig.public.mediaCdnUrl` (default `https://media.negolah.my`),
      pattern `${mediaCdnUrl}/videos/negotiation-demo.mp4`. An explicit `src` prop
      still wins.
- [ ] The `<video>` sets `preload="none"` and attaches **no** `src` / `<source>`
      until the container first intersects the viewport (or `IntersectionObserver`
      is unavailable, or an explicit `src` prop is passed).
- [ ] Re-encoded asset: H.264 High, ≤ 720p, 30 fps, **no audio track**, `moov`
      atom relocated ahead of `mdat` (FastStart), target < 3 MB.
- [ ] R2 bucket `nego-lah-media`; objects uploaded with
      `content-type: video/mp4` and `cache-control: public, max-age=31536000, immutable`.
- [ ] `media.negolah.my` bound to the bucket as a public custom domain on the
      `negolah.my` Cloudflare zone.
- [ ] `backend/scripts/sync_cdn_assets.py` no longer references the video (branding
      logo + mark stay on Supabase — they are embedded in transactional email).
- [ ] `frontend/scripts/sync-media-r2.mjs` uploads every file in the media release
      dir (`~/Desktop/nego-lah-media/dist/`, `masters/` ignored) to
      `r2://nego-lah-media/videos/`, run via `mise run media:sync`.
- [ ] `frontend/public/videos/` is deleted and git-ignored; the master copy lives
      outside the repo (`~/Desktop/nego-lah-media/masters/`).
- [ ] The service-worker media bypass (SPEC-030) still holds: no Workbox route
      matches `media.negolah.my/...*.mp4`.
- [ ] CSP already permits it (`media-src 'self' https: blob:`); no change required.

# Technical Design & Contracts

### URL resolution (`media.negolah.my`)
- Public: `https://media.negolah.my/videos/negotiation-demo.mp4`
- R2 object key: `videos/negotiation-demo.mp4` in bucket `nego-lah-media`
- `runtimeConfig.public.mediaCdnUrl` ← `NUXT_PUBLIC_MEDIA_CDN_URL` || `https://media.negolah.my`

### Lazy load
`shouldLoad` ref, false at mount. Set true when: explicit `src` prop present, OR
`IntersectionObserver` missing, OR the container's first intersection. The
`<source>`/`src` binding and `<video>` render only read a URL once `shouldLoad`.
`preload="none"`; `autoplay`/`loop`/`muted`/`playsinline` unchanged. The existing
bounded retry + `loadeddata` recovery (SPEC-030) is preserved.

### Encode (reference command, run against the master copy)
```
ffmpeg -i negotiation-demo-original.mp4 -an -vf "scale=-2:720,fps=30" \
  -c:v libx264 -profile:v high -preset slow -crf 27 \
  -pix_fmt yuv420p -movflags +faststart negotiation-demo.mp4
```

### Upload (`frontend/scripts/sync-media-r2.mjs`)
Shells `wrangler r2 object put nego-lah-media/videos/<name> --file=<path>
--content-type=<mime> --cache-control="public, max-age=31536000, immutable"
--remote --force` for each file directly in `$MEDIA_SOURCE_DIR` (default
`~/Desktop/nego-lah-media/dist`). Auth is the operator's `wrangler login`
session — this is a rare manual op, so **no API token or Infisical secret** is
involved. Account id / bucket are non-secret constants in the script. If a CI
job ever needs it: add "Workers R2 Storage: Edit" scope to the existing
`CLOUDFLARE_API_TOKEN` **GitHub Actions secret** (already used for the Pages
deploy) — not Infisical `/Frontend`.

### Provisioning status
- ✅ R2 enabled; bucket `nego-lah-media` (account `1468deed5e6c65d715d2d969fb9f1f0e`).
- ✅ Custom domain `media.negolah.my` connected (zone `cb013b3103d86a2ec8fc4d7e3643e246`,
  min-TLS 1.2); serving `HTTP/2 200`, `206` range, `cache-control: ...immutable`.
- ✅ `negotiation-demo.mp4` (1.86 MB) uploaded to `videos/`.
- No Infisical secrets — `media:sync` authenticates via `wrangler login`.
- ⏳ After the frontend deploy lands: delete the stale
  `videos/negotiation-demo.mp4` from the Supabase `images` bucket (staging + prod).

# Test-Driven Development (TDD) Scenarios

- [ ] **Scenario 1:** With no `src` prop and the section off-screen, the rendered
      `<video>` has `preload="none"` and contains no `<source>` and no `src`.
- [ ] **Scenario 2:** After the mocked `IntersectionObserver` reports
      `isIntersecting: true`, a `<source>` appears with
      `https://media.negolah.my/videos/negotiation-demo.mp4`.
- [ ] **Scenario 3:** An explicit `src` prop renders the `<source>` immediately,
      without any intersection.
- [ ] **Scenario 4:** `runtimeConfig.public.mediaCdnUrl` override changes the
      resolved URL host.
- [ ] **Scenario 5:** SPEC-030 regressions still pass — no runtime-caching route
      matches `https://media.negolah.my/videos/negotiation-demo.mp4` or a `.webm`.
- [ ] **Scenario 6:** Existing showcase tests (Memphis SVGs, no controls, retry
      cap, `loadeddata` playback) still pass.

# Implementation Files

- `specs/SPEC-045-r2-media-cdn.md` - This spec
- `docs/adr/0010-cloudflare-r2-media-cdn.md` - Decision record (supersedes the video half of SPEC-028)
- `frontend/app/components/home/ProductVideoShowcase.vue` - CDN URL + lazy load
- `frontend/nuxt.config.ts` - `runtimeConfig.public.mediaCdnUrl`
- `frontend/scripts/sync-media-r2.mjs` - R2 upload via wrangler
- `frontend/tests/components/home/ProductVideoShowcase.test.ts` - Lazy-load + resolution
- `frontend/tests/pwa-runtime-caching.test.ts` - R2 media-bypass regression
- `backend/scripts/sync_cdn_assets.py` - Drop the video asset
- `mise.toml` - `media:sync` task; drop the video from `cdn:sync` messaging
- `.gitignore` - ignore `frontend/public/videos/`
- `specs/SPEC-028-storage-cdn-assets.md` - Mark the video criteria superseded
