# 10. Cloudflare R2 for Large Static Media, Not Supabase Storage

- Status: Accepted
- Date: 2026-09-08
- Deciders: Terry (owner), AI Agent
- Supersedes: the video-delivery portion of SPEC-028 (branding assets on Supabase Storage are unchanged)

## Context

SPEC-028 put the homepage product-walkthrough video (a 12.9 MB MP4) in the
Supabase Storage public `images` bucket alongside the transactional-email
branding assets. `ProductVideoShowcase.vue` autoplays it with `preload="auto"`,
so every homepage visit pulls the full file whether or not the visitor scrolls to
it. In one billing cycle this drove Supabase **cached egress to 6.2 GB against the
Free plan's 5 GB quota (124%)** — enough to throttle the entire project (auth,
database, realtime), since the quota is org-wide.

Storage size was only 57 MB; the cost was purely bandwidth. The branding logo/mark
genuinely need a stable CDN URL (they are `<img src>`-ed inside emails), but the
video is referenced only by the SPA and has no such constraint.

### Decision Drivers

- **Egress cost:** Supabase Storage egress is metered and counts cache hits.
  Cloudflare R2 has **zero egress fees** on all plans.
- **Same edge network:** An R2 bucket with a custom domain is served from the same
  Cloudflare CDN as the Pages deployment, with HTTP range streaming intact.
- **Blast radius:** Media bandwidth spikes must not be able to throttle auth or
  the database.
- **Keep the repo lean:** A multi-megabyte binary does not belong in git history.

## Decision

1. **Cloudflare R2 bucket** `nego-lah-media`, public via the custom domain
   `media.negolah.my` on the existing `negolah.my` zone. Objects carry
   `cache-control: public, max-age=31536000, immutable`.
2. **`ProductVideoShowcase.vue`** resolves `${mediaCdnUrl}/videos/negotiation-demo.mp4`
   from `runtimeConfig.public.mediaCdnUrl` (default `https://media.negolah.my`),
   and **lazy-loads**: `preload="none"`, no `src`/`<source>` attached until the
   section first intersects the viewport.
3. **Re-encode** the asset to 720p30, no audio, H.264 + FastStart (~1.9 MB, down
   from 12.9 MB). WebM/VP9 was measured and rejected — for this screen-recording
   content it is the same size or larger than H.264 at matched quality.
4. **Uploads** via `frontend/scripts/sync-media-r2.mjs` → `mise run media:sync`,
   using `wrangler r2 object put`. Authenticated by the operator's `wrangler
   login` — a rare manual op, so no API token or Infisical secret; account id and
   bucket are non-secret constants. If CI ever runs it, extend the existing
   `CLOUDFLARE_API_TOKEN` GitHub Actions secret with R2 scope.
5. **Remove `frontend/public/videos/` from the repo**; the master copy lives
   outside git. Supabase's `sync_cdn_assets.py` keeps only the branding assets.

## Consequences

- **Positive:** Video egress cost goes to zero and stops counting against the
  Supabase quota. First homepage paint no longer competes with a 13 MB download;
  visitors who never scroll past the hero transfer zero video bytes. Repo checkout
  shrinks by ~13 MB.
- **Negative:** A second storage provider and a second upload path to maintain.
  Local `mise run dev` shows only the poster frame unless `media.negolah.my` is
  reachable (acceptable for a marketing asset).
- **Neutral:** The 13 MB blob remains in git history until a separate history
  rewrite; only new clones' working-tree checkout benefits immediately.
- **Follow-on:** When user-generated media (item photos, avatars) starts driving
  Supabase Storage egress, migrate those to R2 under the same bucket/domain.
