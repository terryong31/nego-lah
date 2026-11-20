---
id: SPEC-116
title: White-Box Security Audit Remediation (2026-11-20)
status: complete
priority: high
created: 2026-11-20
tags: [security, billing, auth, negotiation, media, csp, audit]
assigned: agent
---

# Context & Objectives

The 2026-11-20 white-box security audit (`docs/audits/2026-11-20-white-box-security-audit.md`)
identified ten findings (`SEC-16`..`SEC-25`), led by a re-authentication bypass on
`POST /auth/password/reset` (High), unclamped LLM tool arguments in `evaluate_offer` (High),
EXIF/GPS stripping bypass in `normalize_image` (Medium), incomplete session revocation on admin
ban/delete (Medium), unvalidated admin URL schemes (Medium), and a fail-open metadata fallback in
`POST /payment/confirm-payment` (Low).

This spec closes all actionable backend, frontend, and security-header gaps with TDD coverage.
Removing `'unsafe-inline'`/`'unsafe-eval'` from static Cloudflare Pages CSP remains tracked under
SEC-15's deferred work.

# Acceptance Criteria

- [x] **SEC-16:** `POST /payment/confirm-payment` resolves Stripe PaymentLink metadata via a shared
      helper with `webhooks.py`, fails closed (`400`/`403`) when authoritative metadata lacks
      `item_id` or `user_id` or mismatches the caller, never falls back to client-supplied
      `item_id`, and rejects underpaid sessions below the item's floor price.
- [x] **SEC-17:** Sessions carry `is_recovery` in Redis (`True` only from `/auth/callback` with
      `type="recovery"`). `POST /auth/password/reset` returns `403` for non-recovery sessions and
      clears `is_recovery` after one successful reset.
- [x] **SEC-18:** `evaluate_offer` rejects non-finite `offered_price`, clamps
      `extra_discount_percent` to `[0, 10]`, and anchors strictly to server-side `listed_price` and
      `active_negotiated_price` (ignoring LLM-supplied `current_price` overrides). `create_checkout_link`
      uses `round(agreed_price * 100)`.
- [x] **SEC-19:** `tracking_url` (shipment update) and `avatar_url` (admin profile update) reject
      non-`http`/`https` schemes with `400`. Frontend `orders.vue` and `AdminOrders.vue` only render
      safe `http`/`https` tracking URLs. Production CSP adds `frame-ancestors 'none'` and
      `form-action 'self'` in `frontend/build/csp.ts` and `frontend/public/_headers`.
- [x] **SEC-20:** `core/images.normalize_image` always returns freshly re-encoded bytes so EXIF/GPS
      metadata and trailing payloads are unconditionally stripped.
- [x] **SEC-21:** `user_session._refresh` returns `{}` when a session is revoked during lock wait.
      `ban_user` (on ban), `admin_delete_user`, and `delete_account` revoke all Redis sessions for
      the user; `admin_delete_user` also blocks the deleted user ID in the ban cache and purges
      avatars.
- [x] **SEC-22:** `POST /admin/auth/logout` enforces `verify_csrf_token`.
- [x] **SEC-23:** `core/limiter.py` applies dedicated IP buckets for `/auth` and `/admin/auth`;
      `/auth/register` and `/auth/password/forgot` enforce per-email/IP rate limits; `GET /items/featured`
      (`1..50`) and `GET /chat/history/{user_id}` (`1..100`, `offset >= 0`) enforce query bounds;
      `POST /webhooks/resend` validates `email_id` and caps raw attachment downloads at 25 MB.
- [x] **SEC-24:** `core/security.verify_turnstile` fails closed when `TURNSTILE_HOSTNAMES` is set
      and `hostname` is absent. `fulfill_purchase` auto-refunds a second distinct `payment_intent`
      from the same buyer for an already-sold item.
- [x] **SEC-25:** Admin analyze-image and cleanup-stripe endpoints return generic error messages
      without raw `str(e)`.

# Technical Design & Contracts

- **Billing (`domains/billing/webhooks.py`, `routes.py`, `fulfillment.py`):**
  `resolve_session_metadata(session)` extracts `session.metadata` and falls back to
  `payment_links.retrieve(payment_link_id).metadata` when `payment_link` is set. `confirm_payment`
  requires both `item_id` and `user_id` from Stripe metadata and validates `amount >= floor - 0.01`.
- **Identity (`domains/identity/user_session.py`, `auth_routes.py`, `admin_auth.py`, `admin_users.py`, `routes.py`):**
  `create_session(..., is_recovery=False)` and `open_session_for(..., is_recovery=False)` record
  `is_recovery` in Redis; `clear_recovery_flag(sid)` revokes single-use recovery authority.
- **URL Validation (`core/url.py`, `frontend/app/utils/url.ts`):**
  `is_safe_http_url(url)` validates `http`/`https` scheme with non-empty hostname and no control chars.
- **Negotiation (`domains/negotiation/tools/negotiation.py`, `payment.py`):**
  `MAX_EXTRA_DISCOUNT_PERCENT = 10.0`; `anchor` uses only `[listed_price]` + `[standing_price]`.

# TDD Scenarios

- [x] **SEC-16:** PaymentLink session resolves metadata from `payment_links.retrieve`; missing
      Stripe metadata with query `item_id` returns `400`; underpaid session returns `400`.
- [x] **SEC-17:** Normal login session calling `POST /auth/password/reset` gets `403`; recovery
      callback session succeeds once and a second reset gets `403`.
- [x] **SEC-18:** `evaluate_offer` with `extra_discount_percent=100` clamps to 10%; `current_price=1`
      cannot lower `anchor`; `NaN` offer is rejected cleanly.
- [x] **SEC-19:** `javascript:` in `tracking_url` or `avatar_url` returns `400`; CSP test verifies
      `frame-ancestors 'none'` and `form-action 'self'`.
- [x] **SEC-20:** Low-quality JPEG containing EXIF/GPS metadata has metadata stripped even when
      re-encoding increases byte size.
- [x] **SEC-21:** Revoking a session during `_refresh` lock wait returns `None`; admin ban and
      admin delete revoke active Redis sessions.
- [x] **SEC-22:** `POST /admin/auth/logout` with `admin_sid` cookie and missing/wrong CSRF gets `403`.
- [x] **SEC-23:** Register/forgot rate limits return `429`; `limit=0` / `limit=999` on chat history
      or featured items return `422`; invalid `email_id` or oversized raw download in Resend webhook
      is rejected.
- [x] **SEC-24:** Missing Turnstile `hostname` with `TURNSTILE_HOSTNAMES` set returns `403`;
      same-buyer second distinct `payment_intent` triggers auto-refund.
- [x] **SEC-25:** Admin analyze-image and cleanup-stripe do not leak exception text.

# Implementation Files

- `backend/core/{images,limiter,security,url}.py`
- `backend/domains/billing/{routes,webhooks,fulfillment,admin_routes}.py`
- `backend/domains/identity/{user_session,auth_routes,admin_auth,admin_users,routes}.py`
- `backend/domains/catalog/routes.py`
- `backend/domains/negotiation/{routes,tools/negotiation,tools/payment}.py`
- `backend/domains/webhooks/routes.py`
- `backend/console/admin_listings.py`
- `frontend/build/csp.ts`, `frontend/public/_headers`, `frontend/app/utils/url.ts`,
  `frontend/app/pages/orders.vue`, `frontend/app/components/admin/AdminOrders.vue`
- Tests: `backend/tests/test_security_audit_2026_11_20.py` + updates to existing unit tests and
  `frontend/tests/security-headers.test.ts`
