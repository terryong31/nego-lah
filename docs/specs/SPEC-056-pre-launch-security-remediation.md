---
id: SPEC-056
title: Pre-Launch Security Remediation - CSRF, Fail-Open IDOR, Account Takeover, Payment-Link Spoofing
status: complete
priority: high
created: 2026-09-09
tags: [security, csrf, authorization, account, agent, middleware]
assigned: agent
---

# Context & Objectives

A second full-stack audit (5 days pre-launch) found eight issues. Each was re-verified
against the source before remediation; severities below are **ours**, not the report's,
because two of the reported HIGHs are blunted by controls the report didn't account for.

| # | Reported | Verified | Issue |
|---|---|---|---|
| 1 | HIGH | **MED** | `POST /payment/refund/{item_id}` has `verify_admin` but not `verify_csrf_token`. `SameSite=Lax` blocks the cross-site *form POST*, so this is a broken invariant + defence-in-depth gap, not a live CSRF. |
| 2 | HIGH | **HIGH** | `collect_shipping_info` scopes `buyer_id` only `if user_id:` — SPEC-051 shipped the filter but left it optional. Fail-open. |
| 3 | HIGH | **HIGH** | `PUT /user/{id}/email` takes no `current_password` and passes `email_confirm: True`, so a stolen access token rewrites the account's identity instantly. |
| 4 | HIGH | **HIGH** | `PAY_LINK` promotes *any* `https://` markdown link to a `PayCard` badged "Secured by Stripe". Prompt injection ⇒ a first-party-looking phishing tile. |
| 5 | MED | **LOW** | `RequestDefenseMiddleware` only reads `Content-Length`; `Transfer-Encoding: chunked` and a lying header both slip past. 1.2 GB Lightsail box. |
| 6 | MED | **MED** | Supabase access tokens travel in `?token=` for the SSE stream, landing in access/proxy logs and history. |
| 7 | MED | **LOW** | `DELETE /user/{id}` needs no password; `/user/*` carries no per-IP limit. |
| 8 | LOW | **LOW** | `core/database.py` builds a second pair of Supabase clients at import with `USER_SUPABASE_KEY or ADMIN_SUPABASE_KEY` — the exact fallback SPEC-051 removed from `env.py`. |

# Acceptance Criteria

- [x] **1 — Refund CSRF.** `refund_item` moves to `routes/admin/orders.py` as `POST {ADMIN_PREFIX}/orders/refund/{item_id}`, inheriting `verify_admin` + `verify_csrf_token`. The old `/payment/refund/{item_id}` is gone.
- [x] **2 — Fail closed.** `collect_shipping_info` returns an error and issues **no query** when `get_user_id()` is falsy; the `buyer_id` filter is unconditional.
- [x] **3 — Email change.** `PUT /user/{id}/email` requires `current_password`, verifies it via the anon client, then performs the change **on that user session** so Supabase mails a confirmation link. `email_confirm: True` is gone; response is `{"message", "email", "confirmation_required": true}`.
- [x] **4 — Trusted pay links.** Only `buy.stripe.com` / `checkout.stripe.com` (exact host or subdomain, `https` only) become a `PayCard`. Anything else renders as ordinary link text.
- [x] **5 — Body cap.** The middleware rejects a declared over-limit `Content-Length` (unchanged) **and** caps the actual bytes streamed off the wire, so chunked and under-declared bodies get 413 too.
- [x] **6 — SSE tickets.** `POST /chat/notifications/ticket` (Authorization header) mints a single-use opaque ticket, 30 s TTL in Redis. `/chat/notifications/stream` accepts `?ticket=`; `?token=` is refused.
- [x] **7 — Re-auth + limits.** `DELETE /user/{id}` requires `current_password`. `/user/*` mutations carry `ACCOUNT_LIMIT`.
- [x] **8 — Key hygiene.** `core/database.py` owns the asyncpg pool only; the duplicate Supabase clients are deleted.

# Technical Design & Contracts

**SSE ticket** — `cache.py`
```
mint_sse_ticket(user_id) -> str      # secrets.token_urlsafe(32), SETEX sse:ticket:<t> 30 <user_id>
redeem_sse_ticket(ticket) -> str|None # GETDEL — single use
```
`POST /chat/notifications/ticket` → `{"ticket": str, "expires_in": 30}`.

**Streaming body cap** — wrap the ASGI `receive` callable, summing `http.request` body
lengths; over `limit` returns 413 instead of the next chunk. Catches chunked bodies and
`Content-Length` lies alike, and costs nothing on a request that stays under.

**Trusted pay host** — `frontend/app/utils/chatBlocks.ts`
```ts
const TRUSTED_PAY_HOSTS = ['buy.stripe.com', 'checkout.stripe.com']
isTrustedPaymentUrl(url)  // protocol === 'https:' && (host === h || host.endsWith('.' + h))
```
Untrusted → the segment stays `{type:'text'}` with the raw markdown, so the buyer sees a
plain link and never the Stripe badge.

# Test-Driven Development (TDD) Scenarios

- [x] **S1:** `POST {ADMIN_PREFIX}/orders/refund/x` without `X-CSRF-Token` → 403; with it → 200. `POST /payment/refund/x` → 404.
- [x] **S2:** `collect_shipping_info` with no context user returns an error string and `admin_supabase.table` is never called.
- [x] **S3:** email change without `current_password` → 422; wrong password → 401; correct → `update_user` on the signed-in client, no `email_confirm`.
- [x] **S4:** `messageBlocks` yields `pay` for `buy.stripe.com` and `checkout.stripe.com`; `text` for `evil.com`, `buy.stripe.com.evil.com`, `http://buy.stripe.com`.
- [x] **S5:** chunked POST over the limit → 413; a lying `Content-Length: 10` with a 20 MB body → 413; a small body is untouched.
- [x] **S6:** stream with `?token=` → 401; unknown/reused ticket → 401; fresh ticket → 200 and cannot be redeemed twice.
- [x] **S7:** `DELETE /user/{id}` without password → 422; wrong password → 401.
- [x] **S8:** `core.database` exposes no `admin_supabase` / `user_supabase`.

# Implementation Files

- `backend/routes/admin/orders.py` — refund moved under the CSRF-protected router
- `backend/routes/payment.py` — refund removed
- `backend/agent/tools/payment.py` — fail-closed `buyer_id` scoping
- `backend/routes/user.py` — password re-auth on email change + delete, rate limits
- `backend/schemas.py` — `current_password` on `EmailUpdateSchema`, new `AccountDeleteSchema`
- `backend/core/defense_middleware.py` — streaming body cap
- `backend/cache.py`, `backend/routes/chat.py` — SSE tickets
- `backend/auth_middleware.py` — `get_optional_user_id` no longer reads `?token=`
- `backend/core/database.py` — duplicate Supabase clients deleted
- `frontend/app/utils/chatBlocks.ts` — `isTrustedPaymentUrl`
- `frontend/app/composables/useNotifications.ts` — ticket handshake
- `frontend/app/pages/profile.vue` — current-password fields + confirmation copy
- `docs/adr/0018-pre-launch-security-remediation.md`
