# Comprehensive White-Box Security Audit — 2026-11-20

**Target Systems:**
- Production Frontend: `https://negolah.my` (Cloudflare Pages SPA)
- Production API: `https://api.negolah.my` (FastAPI / Uvicorn on AWS Lightsail)
- Repository: `nego-lah` monorepo

**Scope:** Full-stack white-box review covering the FastAPI modular monolith (`core/`, `domains/`, `console/`), Nuxt 4 SPA (`frontend/`), PostgreSQL Supabase migrations & RLS policies (`supabase/migrations/`), LangGraph/LangChain negotiation tools, Caddy reverse proxy (`Caddyfile`), Docker runtime, GitHub Actions CI/CD, and Python/JS dependency trees.  
**Methodology:** Static source code security audit, control-flow and business-logic threat modeling, dependency auditing (`pip-audit`, `bun audit`), SAST (`bandit`), and AST boundary verification.  
**Reference Standards:** OWASP API Security Top 10 (2023), OWASP Top 10 for LLM Applications (2025), CWE / SANS Top 25, ADR-0002 / ADR-0028 / ADR-0030 / ADR-0032 / ADR-0033.

---

## 1. Executive Summary

A white-box security audit was performed on November 20, 2026, following the previous remediation cycles (`SEC-01`..`SEC-09` in SPEC-104 and `SEC-10`..`SEC-15` in SPEC-110).

### Automated Scanner Baseline
- **Python dependencies (`uv run pip-audit`)**: 0 known vulnerabilities.
- **Python SAST (`uv run bandit`)**: 0 issues across 10,943 lines of production code.
- **Frontend dependencies (`bun audit`)**: 3 advisories (0 critical, 0 high, 2 moderate, 1 low) — `minimatch` (`GHSA-g3hv-75wg-m249`), `glob` (`GHSA-3g3m-2fjr-6pw4`), and `esbuild` (`GHSA-g7r4-m6w7-qqqr`), all confined to build/dev/test tooling rather than the shipped browser bundle.

### Verified Security Controls
- **Database Column & Row Isolation:** `min_price` and `buyer_id` are revoked from `anon` and `authenticated` at the PostgreSQL column-grant level (`20260702000000_items_column_privileges.sql`); soft-deleted items are hidden by RLS; all private tables have RLS enabled with zero client policies; `admin_chat_inbox()` is `SECURITY INVOKER` with `search_path = public` and restricted to `service_role`.
- **Opaque Cookie Sessions & CSRF Isolation:** Both `nl_sid` and `admin_sid` are host-only `httpOnly` opaque session IDs backed by Redis with separate CSRF scopes (`nl_csrf` vs `csrf_token`), server-side PKCE, and Sentry credential scrubbing.
- **Network & Edge Defense:** Caddy trusts Cloudflare IP ranges for `CF-Connecting-IP` and enforces `X-Origin-Auth`; Uvicorn restricts `--forwarded-allow-ips` to the Docker bridge; `RequestDefenseMiddleware` meters raw ASGI body chunks against chunked payload bombs; `link_guard.py` + `isTrustedPaymentUrl` block fabricated payment cards.

### Audit Findings Summary Matrix

| Finding ID | Vulnerability / Issue Title | Category | Severity | CWE | Affected File(s) |
|---|---|---|---|---|---|
| **SEC-16** | Fail-Open Metadata Fallback in `POST /payment/confirm-payment` | Defense-in-Depth / Billing | **Low** | CWE-636 / CWE-639 | `backend/domains/billing/routes.py`, `backend/domains/billing/webhooks.py` |
| **SEC-17** | Re-Authentication Bypass via `POST /auth/password/reset` on Non-Recovery Sessions | Authentication / Account Takeover | **High** | CWE-287 / CWE-306 | `backend/domains/identity/auth_routes.py`, `backend/domains/identity/user_session.py` |
| **SEC-18** | Prompt-Injection Negotiation Bypass & Floor Oracle via Unclamped `evaluate_offer` Args | AI / LLM Tool Security | **High** | CWE-20 / CWE-840 | `backend/domains/negotiation/tools/negotiation.py`, `backend/domains/negotiation/tools/payment.py` |
| **SEC-19** | Unvalidated Admin URL Schemes (`tracking_url`, `avatar_url`) & Missing CSP Framing/Form Directives | Client Security / XSS Defense | **Medium** | CWE-79 / CWE-1021 | `backend/domains/billing/admin_routes.py`, `backend/domains/identity/admin_users.py`, `frontend/build/csp.ts`, `frontend/public/_headers`, `frontend/app/pages/orders.vue`, `frontend/app/components/admin/AdminOrders.vue` |
| **SEC-20** | EXIF / GPS Metadata Stripping Bypass When Re-Encoded Image Is Larger | Privacy / Media Sanitization | **Medium** | CWE-200 / CWE-434 | `backend/core/images.py` |
| **SEC-21** | Incomplete Session Revocation on Admin Delete/Ban & Concurrent Refresh Race | Session Management | **Medium** | CWE-613 | `backend/domains/identity/admin_users.py`, `backend/domains/identity/routes.py`, `backend/domains/identity/user_session.py` |
| **SEC-22** | Missing CSRF Protection on `POST /admin/auth/logout` | CSRF | **Low** | CWE-352 | `backend/domains/identity/admin_auth.py` |
| **SEC-23** | Unbounded Pagination, Coarse Auth IP Buckets & Uncapped Inbound Email Attachment Downloads | Resource Exhaustion / Abuse | **Low** | CWE-400 / CWE-307 | `backend/core/limiter.py`, `backend/domains/identity/auth_routes.py`, `backend/domains/catalog/routes.py`, `backend/domains/negotiation/routes.py`, `backend/domains/webhooks/routes.py` |
| **SEC-24** | Turnstile Hostname Check Fail-Open & Same-Buyer Double-Payment Gap | Defense-in-Depth / Billing | **Low** | CWE-636 / CWE-840 | `backend/core/security.py`, `backend/domains/billing/fulfillment.py` |
| **SEC-25** | Admin Raw Exception Leakage & Frontend Dev Toolchain Advisories | Information Exposure / Supply Chain | **Low** | CWE-209 / CWE-1104 | `backend/console/admin_listings.py`, `backend/domains/billing/admin_routes.py`, `frontend/package.json` |

---

## 2. In-Depth Vulnerability Analysis

### SEC-16: Fail-Open Metadata Fallback in `POST /payment/confirm-payment`
- **Severity:** **Low** (Defense-in-Depth)
- **CWE:** CWE-636 (Not Failing Securely), CWE-639 (Authorization Bypass Through User-Controlled Key)
- **Locations:** `backend/domains/billing/routes.py`, `backend/domains/billing/webhooks.py`

#### Description
Stripe automatically propagates `metadata` from a PaymentLink onto the resulting Checkout Session, so normal AI-generated PaymentLinks (`create_checkout_link`) and Buy Now sessions (`create_checkout_session`) both arrive with `item_id` and `user_id` populated on `session.metadata` (note: the existing comment in `webhooks.py:25` stating PaymentLinks do not propagate metadata to the Session is inaccurate—only retroactive edits or links created without metadata lack it).

However, `POST /payment/confirm-payment` still fails open whenever `session.metadata` is missing `item_id` or `user_id`:
- `item_id = stripe_get(metadata, "item_id") or item_id` falls back to the untrusted client query parameter.
- `if session_user_id and session_user_id != user_id:` skips buyer verification when `session_user_id` is absent.

#### Impact
Not exploitable against standard Checkout Sessions or PaymentLinks created by this backend (Stripe supplies both metadata keys). However, if any paid Checkout Session ever exists on the same Stripe account without `item_id`/`user_id` metadata (e.g., a Dashboard-created Payment Link or legacy/out-of-band link), `confirm_payment` would trust the caller's `item_id` query parameter and skip the buyer ownership check.

#### Remediation
1. Share a single `resolve_session_metadata(session)` helper between `webhooks.py` and `routes.py` (and correct the misleading comment in `webhooks.py`).
2. Fail closed in `confirm_payment`: never fall back to client-supplied `item_id` or `user_id`. Require both from Stripe's authoritative metadata and enforce `session_user_id == token_user_id`.
3. Add a defensive check that `amount_total / 100` is at least the item's `floor_price` before fulfilling.

---

### SEC-17: Re-Authentication Bypass via `POST /auth/password/reset` on Non-Recovery Sessions
- **Severity:** **High**
- **CWE:** CWE-287 (Improper Authentication), CWE-306 (Missing Authentication for Critical Function)
- **Locations:** `backend/domains/identity/auth_routes.py`, `backend/domains/identity/user_session.py`

#### Description
`POST /auth/password/reset` allows setting a new password without supplying `current_password`, relying on the assumption that the caller holds a recovery session minted by `/auth/callback?type=recovery`. However, `create_session()` and `open_session_for()` do not record whether a session originated from a recovery link. Any standard login or Google OAuth session passes `read_session(sid)`.

#### Impact
Anyone with temporary access to a logged-in session (such as an unlocked device or an XSS vector) can call `POST /auth/password/reset` to replace the victim's password without knowing the old password, evict the victim's other sessions via `revoke_other_sessions`, and subsequently satisfy `_reauthenticate()` on `PUT /user/{id}/email` or `DELETE /user/{id}` for permanent account takeover.

#### Remediation
1. Store `"is_recovery": bool(is_recovery)` in the Redis session record, set to `True` **only** when `/auth/callback` verifies `type == "recovery"`.
2. Reject `POST /auth/password/reset` with `403` unless `stored.get("is_recovery") is True`.
3. Clear `is_recovery` immediately after a successful reset so the recovery capability is single-use.

---

### SEC-18: Prompt-Injection Negotiation Bypass & Floor Oracle via Unclamped `evaluate_offer` Args
- **Severity:** **High**
- **CWE:** CWE-20 (Improper Input Validation), CWE-840 (Business Logic Errors)
- **Locations:** `backend/domains/negotiation/tools/negotiation.py`, `backend/domains/negotiation/tools/payment.py`

#### Description
`evaluate_offer` accepts two LLM-controlled numeric arguments without server-side constraints:
1. `extra_discount_percent` is documented as `0`, `5`, or `10`, but is unclamped in Python. A prompt-injected model passing `extra_discount_percent=100` drops `adjusted_threshold` immediately to `min_price`.
2. `current_price` is unconditionally appended to `candidates`, allowing a manipulated model passing a low value (e.g. `1`) to drop `anchor` straight to `min_price` in a single turn.
3. Because the `REJECT_FLOOR` response includes `anchor` only when `anchor > min_price`, probing `current_price` also leaks whether a candidate price is above or at/below `min_price`.
4. Separately, `create_checkout_link` computes Stripe cents with `int(agreed_price * 100)` instead of `round(agreed_price * 100)`, risking 1-sen IEEE-754 truncation.

#### Impact
Although `create_checkout_link` and `/payment/checkout` prevent sales *below* `min_price`, prompt injection can collapse the entire multi-round concession strategy in one turn, commit `min_price` into Redis (`negotiated_price:{user_id}:{item_id}`), and unlock **Buy Now** at the floor immediately.

#### Remediation
1. Reject non-finite `offered_price` values (`math.isfinite`) and clamp `extra_discount_percent` server-side to `[0.0, 10.0]`.
2. Make server state (`listed_price` and `BillingService.get_active_negotiated_price`) the sole authority for `anchor`, ignoring LLM-supplied `current_price` downward overrides.
3. Use `round(agreed_price * 100)` in `create_checkout_link`.

---

### SEC-19: Unvalidated Admin URL Schemes (`tracking_url`, `avatar_url`) & CSP Directives
- **Severity:** **Medium**
- **CWE:** CWE-79 (Cross-Site Scripting), CWE-1021 (Improper Restriction of Rendered UI Layers)
- **Locations:** `backend/domains/billing/admin_routes.py`, `backend/domains/identity/admin_users.py`, `frontend/build/csp.ts`, `frontend/public/_headers`, `frontend/app/pages/orders.vue`, `frontend/app/components/admin/AdminOrders.vue`, `frontend/app/pages/items/[id].vue`

#### Description
1. `PUT /admin/orders/{order_id}/shipment` accepts an explicit `tracking_url` and `PUT /admin/users/{user_id}/profile` accepts an explicit `avatar_url` without validating the URL scheme. `orders.vue` and `AdminOrders.vue` render `tracking_url` directly into `:to`.
2. Production CSP omits `frame-ancestors 'none'` and `form-action 'self'` (relying only on legacy `X-Frame-Options: DENY`). As noted in `SEC-15`, removing `'unsafe-inline'` / `'unsafe-eval'` from static Cloudflare Pages builds remains tracked separately.
3. Item descriptions rendered through `<MDC :value="localizedDescription" />` should remain constrained against raw HTML / arbitrary component injection.

#### Remediation
1. Enforce an `http://` / `https://` URL validator with a non-empty host on `tracking_url` and `avatar_url` in the backend (`400` on invalid schemes like `javascript:` or `data:`), and gate `tracking_url` on the frontend with an `https?:` check before rendering a link.
2. Add `frame-ancestors 'none'` and `form-action 'self'` to `frontend/build/csp.ts` and `frontend/public/_headers`.

---

### SEC-20: EXIF / GPS Metadata Stripping Bypass When Re-Encoded Image Is Larger
- **Severity:** **Medium**
- **CWE:** CWE-200 (Exposure of Sensitive Information), CWE-434 (Unrestricted Upload of File with Dangerous Type)
- **Location:** `backend/core/images.py`

#### Description
`normalize_image()` is relied on to strip EXIF metadata (including phone GPS coordinates) and non-pixel trailing payloads by decoding and re-encoding every image. However, when `len(encoded) >= len(data)` for non-HEIC formats, it falls back to returning the original untouched `data` bytes. Already-compressed or small JPEGs containing EXIF GPS tags frequently expand slightly at quality 82 and therefore publish raw metadata to the public R2 CDN (`media.negolah.my`).

#### Remediation
Always return the freshly re-encoded image bytes (`encoded, content_type, ext`) so EXIF/GPS metadata and trailing payloads are unconditionally stripped on every upload.

---

### SEC-21: Incomplete Session Revocation on Admin Delete/Ban & Concurrent Refresh Race
- **Severity:** **Medium**
- **CWE:** CWE-613 (Insufficient Session Expiration)
- **Locations:** `backend/domains/identity/admin_users.py`, `backend/domains/identity/routes.py`, `backend/domains/identity/user_session.py`

#### Description
1. `DELETE /admin/users/{user_id}` deletes the Supabase Auth user and `user_profiles` row without revoking Redis sessions (`revoke_other_sessions`), setting `cache_ban_status(user_id, True)`, or purging R2 avatars. Because `user_profiles` is gone, `_is_user_banned` returns `False`, allowing active `nl_sid` cookies to keep authenticating until token refresh fails.
2. `PUT /admin/users/{user_id}/ban` invalidates the ban cache but leaves Redis sessions intact (affecting `/auth/session`, which reads Redis directly). Self-service `DELETE /user/{user_id}` also did not invoke `revoke_other_sessions` to immediately wipe other devices' Redis sessions.
3. In `user_session._refresh()`, when a waiting request sees `fresh is None` (the session was logged out or revoked while waiting for the refresh lock), it returns the stale in-memory `session` dict instead of `{}`.

#### Remediation
1. Return `{}` when `fresh is None` inside `user_session._refresh()`.
2. Revoke all Redis sessions (`revoke_other_sessions(user_id, keep_sid=None)`) in `ban_user` (when banning), `admin_delete_user`, and `delete_account`.
3. Also set the deleted-account ban cache and purge avatars in `admin_delete_user`.

---

### SEC-22: Missing CSRF Protection on `POST /admin/auth/logout`
- **Severity:** **Low**
- **CWE:** CWE-352 (Cross-Site Request Forgery)
- **Location:** `backend/domains/identity/admin_auth.py`

#### Description
Because `admin_auth.router` is mounted outside the `protected` router in `console/admin_api.py`, `POST /admin/auth/logout` enforces `verify_admin` without `verify_csrf_token`, allowing cross-site forced logout.

#### Remediation
Add `dependencies=[Depends(verify_csrf_token)]` to `@router.post("/auth/logout")`.

---

### SEC-23: Unbounded Pagination, Coarse Auth IP Buckets & Uncapped Inbound Email Attachment Downloads
- **Severity:** **Low**
- **CWE:** CWE-400 (Uncontrolled Resource Consumption), CWE-307 (Improper Restriction of Excessive Authentication Attempts)
- **Locations:** `backend/core/limiter.py`, `backend/domains/identity/auth_routes.py`, `backend/domains/catalog/routes.py`, `backend/domains/negotiation/routes.py`, `backend/domains/webhooks/routes.py`

#### Description
1. `/auth/*` and `/admin/auth/*` fall into `DEFAULT_LIMIT` (`10,000/minute`), and `/auth/register` + `/auth/password/forgot` have no application-level rate limit if Turnstile fails open on a transport error.
2. `GET /items/featured?limit=` and `GET /chat/history/{user_id}?limit=0&offset=` lack upper/lower bounds (`limit=0` disables `.range()` pagination in `ConversationMemory._page`).
3. `POST /webhooks/resend` interpolates `email_id` into the Resend API URL without format validation and downloads raw email attachments into memory with no size cap.

#### Remediation
1. Add dedicated `/auth` and `/admin/auth` IP rate-limit buckets in `core/limiter.py` plus per-email/IP rate limits on `/auth/register` and `/auth/password/forgot`.
2. Add `Query(ge=..., le=...)` bounds on `GET /items/featured` and `GET /chat/history/{user_id}`.
3. Validate `email_id` format and enforce a maximum raw email download size (`MAX_INBOUND_RAW_BYTES = 25 MB`) in `domains/webhooks/routes.py`.

---

### SEC-24: Turnstile Hostname Check Fail-Open & Same-Buyer Double-Payment Gap
- **Severity:** **Low**
- **CWE:** CWE-636 (Not Failing Securely), CWE-840 (Business Logic Errors)
- **Locations:** `backend/core/security.py`, `backend/domains/billing/fulfillment.py`

#### Description
1. In `core/security.py`, `if expected_hostnames and outcome.get("hostname"):` skips hostname verification if the `hostname` key is missing or empty in Cloudflare's response.
2. In `fulfill_purchase`, when an item is already `sold` to `buyer_id == user_id`, any second distinct `payment_intent` from that same buyer is treated as `"duplicate"` rather than auto-refunded.

#### Remediation
1. Check `if expected_hostnames:` unconditionally and reject missing/mismatched `hostname`.
2. When `item_row.get("buyer_id") == user_id`, check whether this `payment_intent` belongs to an existing order or whether a different non-refunded `stripe_payment_id` already won the item; auto-refund the second distinct charge.

---

### SEC-25: Admin Raw Exception Leakage & Frontend Dev Toolchain Advisories
- **Severity:** **Low**
- **CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information), CWE-1104 (Use of Unmaintained Third Party Components)
- **Locations:** `backend/console/admin_listings.py`, `backend/domains/billing/admin_routes.py`, `frontend/package.json`

#### Description
1. `POST /admin/analyze-image`, `POST /admin/analyze-image/stream`, and `POST /admin/cleanup-stripe` return raw `str(e)` strings in error responses rather than logging internally and returning generic messages.
2. `bun audit` reports 3 moderate/low advisories in build/dev dependencies (`minimatch`, `glob`, `esbuild`).

#### Remediation
1. Return generic error messages from admin endpoints while keeping detailed exception text in logs.
2. Track/update dev toolchain overrides as upstream patched versions become compatible, keeping `bun audit --audit-level=high` green in CI.

---

## 3. Remediation Tracking

All findings (`SEC-16` through `SEC-25`) are tracked and remediated under [SPEC-116](../specs/SPEC-116-white-box-audit-2026-11-20.md).
