---
id: SPEC-028
title: Supabase Storage CDN Assets and FastStart Video Streaming
status: complete
priority: medium
created: 2026-09-06
tags: [storage, cdn, streaming, emails]
assigned: agent
---

# Context & Objectives
Serve static branding assets (logo for transactional emails) and the product demo walkthrough video from Supabase Storage's global CDN across staging and production environments. Optimize the demo video for instant progressive streaming via HTTP 206 byte-range requests by reorganizing MP4 atom indices with FastStart.

> **Superseded in part by [SPEC-045](SPEC-045-r2-media-cdn.md) (2026-09-08):** the demo
> walkthrough video moved off Supabase Storage to a zero-egress Cloudflare R2
> bucket (`media.negolah.my`) after one 13 MB asset exhausted the Supabase Free
> plan's 5 GB egress quota. The FastStart criterion and the
> `videos/negotiation-demo.mp4` upload below no longer apply. The **branding
> assets** (`branding/logo.png`, `branding/mark.svg`) stay on Supabase Storage —
> transactional email embeds them by absolute URL.

# Acceptance Criteria
- [ ] MP4 video has the `moov` index atom relocated before the `mdat` payload (FastStart), enabling instant progressive HTTP streaming without full download.
- [ ] `branding/logo.png`, `branding/mark.svg`, and `videos/negotiation-demo.mp4` are uploaded to the public `images` bucket in both Supabase staging (`dev`) and production (`prod`).
- [ ] Objects are uploaded with `cache-control: public, max-age=31536000, immutable`.
- [ ] Email templates (`base.html`, `magic_link.html`) render the high-DPI brand logo from the CDN with graceful fallbacks.
- [ ] `backend/services/email_service.py` automatically injects `brand_logo_url` into template context.
- [ ] `ProductVideoShowcase.vue` defaults its video source to the Supabase CDN URL when runtime configuration is present, falling back to local `/videos/negotiation-demo.mp4`.
- [ ] Idempotent CLI script `backend/scripts/sync_cdn_assets.py` managed via `mise run cdn:sync`.

# Technical Design & Contracts
### Storage Paths (`images` bucket)
- `branding/logo.png` (`image/png`)
- `branding/mark.svg` (`image/svg+xml`)
- `videos/negotiation-demo.mp4` (`video/mp4`)

### CDN URL Resolution
- Pattern: `${SUPABASE_URL}/storage/v1/object/public/images/${path}`
- Staging Host: `https://cecuhsexmqtjrwuqaavz.supabase.co`
- Production Host: `https://umtsegjkgpfefjvhyysh.supabase.co`

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1:** `backend/tests/test_email_service.py` verifies that `render_email_template` injects `brand_logo_url` and renders `<img ...>` in `base.html`.
- [ ] **Scenario 2:** `frontend/tests/components/home/ProductVideoShowcase.test.ts` verifies that `ProductVideoShowcase` constructs the Supabase CDN video URL when `supabase.url` is configured.
- [ ] **Scenario 3:** Verify HTTP 206 Partial Content range requests against the uploaded video on both CDNs.

# Implementation Files
- `backend/scripts/sync_cdn_assets.py` - FastStart optimization & Supabase storage sync
- `mise.toml` - Orchestration tasks for staging & prod sync
- `backend/services/email_service.py` - Context injection for brand logo CDN URL
- `backend/templates/emails/base.html` - Email header brand logo image tag
- `supabase/templates/magic_link.html` - Supabase Auth magic link brand logo image tag
- `frontend/app/components/home/ProductVideoShowcase.vue` - Dynamic CDN video source resolution
- `frontend/public/videos/negotiation-demo.mp4` - FastStart optimized local asset
