---
id: SPEC-110
title: Password Changes End Other Sessions, Refunds Replay, Chat Attachments Are Bounded
status: complete
priority: medium
created: 2026-10-27
tags: [security, auth, billing, chat, cookies, audit]
assigned: agent
---

# Context & Objectives

The 2026-10-27 white-box audit (`docs/audits/2026-10-27-comprehensive-white-box-audit.md`)
raised SEC-10..SEC-15. Each was checked against the code before fixing:

- **SEC-10 (valid).** Buyer sessions are keyed only by sid, so a password change or reset could not
  find the user's other sessions. `resolve_user_id` trusts Redis without asking Supabase, so another
  device stayed signed in at least until its access token's next refresh, and for the full sliding
  30 days if Supabase kept honouring its refresh token.
- **SEC-11 (valid, impact overstated).** `process_refund` always refunds the whole PaymentIntent, so
  Stripe already refuses a second one (`charge_already_refunded`). The real failure: a refund that
  lands on Stripe but whose response is lost leaves the item sold and the order unrefunded, and the
  retry only gets an error. An idempotency key makes the retry replay the first result.
- **SEC-12 (valid).** `/chat/stream` took any number of files and passed images to the vision model
  undecoded. The SPA never sends attachments, so only direct API callers hit this. The filename
  sat outside the 4,000-character message cap.
- **SEC-13 (valid).** `nl_sid` and `admin_sid` defaulted to `Domain=.negolah.my`, so they were sent to
  every subdomain. Only `api.negolah.my` reads them.
- **SEC-14 (valid).** Buyer login had only Turnstile and the per-IP limiter. The audit's sketch
  (10 per 15 min, keyed on the email alone) would let anyone lock a buyer out; this follows the
  admin login's email+IP and per-account pair instead.
- **SEC-15 (valid, deferred).** Removing `'unsafe-inline'`/`'unsafe-eval'` needs nonces or hashes on a
  static Cloudflare Pages build. It is informational and gets its own spec.

# Acceptance Criteria

- [x] Each new buyer session is indexed under `user:sids:<user_id>`; the index slides with the session.
- [x] `PUT /user/{id}/password` and `POST /auth/password/reset` revoke every other session of that
      user. The session that made the change stays.
- [x] `destroy_session` drops the sid from the index.
- [x] `scripts/revoke_all_sessions.py` also clears `user:sids:*`.
- [x] Admin refunds pass `idempotency_key=f"admin_refund_{payment_id}"`.
- [x] `/chat/stream` rejects more than `CHAT_MAX_ATTACHMENTS` (4) files with a 400.
- [x] Image attachments are decoded and re-encoded by `normalize_image` (≤1024 px). Bytes that do not
      decode get a 400. Filenames are stripped of control characters and capped at 100 chars.
- [x] `USER_COOKIE_DOMAIN` and `ADMIN_COOKIE_DOMAIN` default to host-only. `CSRF_COOKIE_DOMAIN` stays
      `.negolah.my` because the SPA reads it.
- [x] Setting or clearing a session cookie also expires the copy under the old `.negolah.my`
      domain, so a pre-deploy cookie cannot survive sign-out. This cleanup can be removed after 2026-12-01.
- [x] `POST /auth/login` is limited to 10 attempts per 15 min per email+IP and 30 per email from any
      address. Over the limit it returns 429 before Supabase is called.

# Technical Design & Contracts

- `user_session.revoke_other_sessions(user_id, keep_sid) -> int`: reads the index (a sorted set
  scored by creation time, which works with the in-memory Redis stand-in) and destroys each sid.
- `env.LEGACY_SESSION_COOKIE_DOMAIN`: the old default. It is only used to expire cookies and is
  `None` when it equals the configured domain.
- The login limiter counts every attempt, like the admin one.

# TDD Scenarios

- Three sessions for one user plus one for another user. Changing or resetting the password leaves
  only the caller's session and the other user's session.
- Logout removes the sid from the index. A slide extends the index TTL.
- The refund passes an idempotency key derived from the PaymentIntent.
- Five files get a 400. A PNG is re-encoded. Junk bytes labelled `image/png` get a 400. A
  300-character filename with a newline is cleaned.
- Default cookie domains are host-only. Login and logout responses expire the legacy-domain cookie.
- The 11th login attempt from one email+IP gets a 429 and Supabase is not called.

# Implementation Files

- `backend/domains/identity/{user_session,routes,auth_routes,admin_session}.py`, `backend/core/env.py`
- `backend/domains/billing/refunds.py`, `backend/domains/negotiation/routes.py`
- `backend/scripts/revoke_all_sessions.py`
- Tests: `test_user_session.py`, `test_auth_routes.py`, `test_routes_user.py`, `test_payment_refunds.py`,
  `test_routes_chat.py`, `test_admin_session.py`, `test_scripts_revoke_all_sessions.py`
