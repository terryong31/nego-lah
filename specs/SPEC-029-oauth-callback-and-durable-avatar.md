---
id: SPEC-029
title: OAuth callback UX and durable custom avatar
status: complete
priority: high
created: 2026-09-06
tags: [identity, auth, frontend, backend]
assigned: agent
---

# Context & Objectives

Two defects in the Google sign-in path, sharing a root cause of "the OAuth flow
is treated as if it were the email-confirmation flow".

1. **`/confirm` shows "Email Confirmed!" after every Google login.** `/confirm`
   is the single Supabase auth callback route (`redirectOptions.callback` plus
   the explicit `redirectTo` on the Google button), so OAuth legitimately lands
   there to exchange the PKCE code. But the success branch is hardcoded to the
   email-verification copy and a 5s countdown, so a Google user is told their
   email was verified and then made to wait before reaching the app.

2. **A Google login overwrites the user's uploaded profile picture.** Supabase
   refreshes `user_metadata` from the identity provider's claims on every OAuth
   sign-in. Google's claims include `avatar_url` / `picture`, which clobbers the
   value written by `PUT /user/{id}/profile`. The uploaded image survives in
   storage but stops being referenced.

# Acceptance Criteria

- [x] Completing a Google sign-in redirects straight to the target page; the
      "Email Confirmed!" screen and countdown never render for that flow.
- [x] The email-confirmation flow (`token_hash` / `type`, or a code exchange not
      marked as OAuth) still shows the existing success screen unchanged.
- [x] The OAuth redirect replaces `/confirm` in history rather than pushing, so
      Back does not return to the callback route.
- [x] An uploaded avatar is stored under a metadata key Google does not write,
      and survives logout + Google re-login.
- [x] A user who has never uploaded an avatar still shows their Google picture.
- [x] Header, profile page, admin user list and admin chat list all resolve the
      avatar through one shared helper per stack.
- [x] A re-runnable, dry-run-by-default script migrates uploads that Google has
      not overwritten yet.

# Technical Design & Contracts

**Flow marker.** `pages/login.vue` already appends `?redirect=` to the OAuth
`redirectTo`; add `flow=oauth` the same way. `pages/confirm.vue` treats the flow
as OAuth when that marker is present, or when the established session's
`app_metadata.provider` is anything other than `email`.

**Avatar key.** `PUT /user/{user_id}/profile` writes the uploaded URL to
`user_metadata.custom_avatar_url` instead of `avatar_url`. Google owns
`avatar_url`; it never writes `custom_avatar_url`, so the custom value is
durable. The response contract is unchanged — `avatar_url` in the JSON body
remains the *effective* avatar.

Resolution order everywhere: `custom_avatar_url` → `avatar_url` → (backend only)
legacy `user_profiles.avatar_url`.

- `frontend/app/utils/auth.ts` — `resolveAvatarUrl(user)`
- `backend/routes/admin.py` — `_resolve_avatar_url(meta, profile)`

No database migration: both keys live in the existing auth `user_metadata` JSON.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `confirm.vue` with `flow=oauth` and a session redirects via
      `router.replace` without rendering "Email Confirmed!".
- [x] **Scenario 2:** `confirm.vue` with `flow=oauth` and `redirect=/orders`
      replaces to `/orders`.
- [x] **Scenario 3:** `confirm.vue` without the marker still renders the success
      screen and the countdown (existing tests stay green).
- [x] **Scenario 4:** `login.vue`'s Google button passes a `redirectTo`
      containing `flow=oauth`.
- [x] **Scenario 5:** `resolveAvatarUrl` prefers `custom_avatar_url`, falls back
      to `avatar_url`, returns `undefined` when neither is set.
- [x] **Scenario 6:** `PUT /user/{id}/profile` with an avatar writes
      `custom_avatar_url` into the submitted metadata and returns it as
      `avatar_url`.
- [x] **Scenario 7:** That call preserves a Google-supplied `avatar_url` already
      in metadata rather than deleting it.
- [x] **Scenario 8:** Admin `/users` and `/chats` report `custom_avatar_url` in
      preference to a Google `avatar_url`.
- [x] **Scenario 9:** The backfill matches only this project's own storage URLs
      under `avatars/`, never a provider photo, another project, or an item image.
- [x] **Scenario 10:** It writes nothing without `--apply`, preserves the rest of
      the metadata when it does, skips already-migrated users, paginates, and
      carries on past a user whose update fails (exiting non-zero).

# Implementation Files

- `frontend/app/pages/login.vue` - tag the OAuth `redirectTo` with `flow=oauth`
- `frontend/app/pages/confirm.vue` - skip the success screen on the OAuth flow
- `frontend/app/utils/auth.ts` - `resolveAvatarUrl` helper
- `frontend/app/components/AppHeader.vue` - resolve avatar via the helper
- `frontend/app/pages/profile.vue` - resolve avatar via the helper
- `backend/routes/user.py` - write `custom_avatar_url`
- `backend/routes/admin.py` - `_resolve_avatar_url` for user + chat listings
- `backend/scripts/backfill_custom_avatar.py` - one-off migration for existing uploads
- `mise.toml` - `avatars:backfill` / `avatars:backfill:apply` tasks

# Notes

`scripts/backfill_custom_avatar.py` migrates the still-intact uploads — users
who have not signed in with Google since uploading. It tells a self-upload from a
provider photo by URL prefix (this project's storage bucket, `avatars/` folder),
defaults to a dry run, and skips anyone already carrying a `custom_avatar_url`,
so it is safe to re-run. `mise run avatars:backfill` reports;
`mise run avatars:backfill:apply` writes.

A user whose `avatar_url` was *already* overwritten by Google has lost the
reference entirely — no migration can recover it, and they need to re-upload
once.

The purchase-confirmation email asked for alongside these fixes already exists —
`send_purchase_receipt` (services/email_service.py) fires from
`_finalize_won_sale` on the one-time fulfilment transition, which both the Stripe
webhook and the frontend confirm route funnel through. No work was needed.
