---
id: SPEC-108
title: User Media Is Served from a First-Party CDN and Stored as Keys
status: in-progress
priority: high
created: 2026-10-14
tags: [media, storage, security, catalog, identity, bff]
assigned: agent
---

# Context & Objectives

Uploads already go through FastAPI, but reads do not: the backend stores Supabase public URLs and
the SPA `<img>`s `https://<project>.supabase.co/…` directly — the one place the browser still talks
to Supabase (ADR-0028). It went unnoticed because `img-src` allows any `https:` host. The same URLs
reach `og:image`, the agent's vision input and the email logo, which also hardcodes the project id.

Adopt the standard user-media setup (ADR-0033): the API authorises writes, a CDN on our own domain
serves bytes, rows hold object keys, and every object name is unique so it can be cached forever.
ADR-0010 already named this follow-on.

# Acceptance Criteria

- [x] Every upload (item photos, self-service avatar, admin avatar, branding) goes to the R2 bucket
      behind `MEDIA_CDN_URL`; no production code outside `core/media.py` touches `.storage`.
- [x] Every object name is unique (`items/<id>/<rand>.<ext>`, `avatars/<user>/<rand>.<ext>`) and is
      written with `cache-control: public, max-age=31536000, immutable`.
- [x] New rows store keys, not URLs; every read path resolves through `media_url()`.
- [x] Legacy Supabase URLs still in rows resolve to the same key on the CDN, so the deploy does not
      wait on a data rewrite.
- [x] Foreign URLs (a Google avatar, an admin-pasted URL) and `data:` URLs pass through untouched.
- [x] Account deletion removes the user's avatar objects, including legacy admin uploads that were
      named `avatars/<user>_<rand>`.
- [x] `scripts/migrate_media_to_r2.py` copies the bucket (idempotent) and rewrites rows to keys;
      dry run by default.
- [x] The email logo resolves through `media_url()`; no Supabase project id in source.
- [ ] Rollout: R2 token in Infisical, `copy --apply` before the deploy, `rewrite --apply` after.
- [ ] Phase 2 (separate PR, after prod is verified): `img-src`/`media-src` narrowed to first-party
      hosts and the Google avatar host; the Supabase bucket's public-read policy dropped.

# Technical Design & Contracts

`core/media.py`:
- `media_key(value) -> str | None` — the key a stored value names: a bare key, our CDN URL, or a
  legacy `{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/…` URL. Anything else → `None`.
- `media_url(value)` — `MEDIA_CDN_URL/<key>` when `media_key` finds one, else `value` unchanged.
- `media_store.put(key, body, content_type)`, `.delete(keys)`, `.list(prefix)`, `.exists(key)` —
  the S3 API on R2, SigV4 over `httpx` (no `boto3`: ~70 MB RSS per worker on a 2 GB box).
  Synchronous; callers keep their `asyncio.to_thread`.

Env: `MEDIA_CDN_URL` (default `https://media.negolah.my`), `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.

Rollout: copy objects → deploy (reads both forms, writes R2) → rewrite rows → phase 2.

# TDD Scenarios

- SigV4 signature equals botocore's for a fixed clock (recorded vector).
- `media_key`/`media_url` over bare keys, CDN URLs, legacy URLs (with Supabase's trailing `?`),
  another project's URL, Google URLs, `data:`, `None`, and path traversal (`../`).
- Item create/edit: keys stored, unique names, kept photos matched by CDN *or* legacy URL, dropped
  photos deleted by key; the public serializer emits CDN URLs only.
- Avatars: self-service and admin uploads store keys; session payload, profile response and
  `resolve_avatar_url` emit CDN URLs; deletion purges both prefixes.
- AST scan: no `.storage` / `get_public_url` outside `core/media.py`.

# Implementation Files

- `backend/core/media.py`, `backend/core/env.py`, `backend/core/email_service.py`
- `backend/domains/catalog/{items,routes}.py`, `backend/domains/billing/routes.py`,
  `backend/domains/negotiation/bot.py`
- `backend/domains/identity/{routes,admin_users,auth_routes,profiles}.py`
- `backend/scripts/{migrate_media_to_r2,sync_cdn_assets}.py`, `backend/.env.example`
- `docs/adr/0033-user-media-on-a-first-party-cdn.md`, `docs/data/README.md`
