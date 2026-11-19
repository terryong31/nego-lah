---
id: SPEC-114
title: StripeClient v1 Checkout Fix & Generic Frontend Error Toasts
status: complete
priority: high
created: 2026-11-19
tags: [billing, stripe, frontend, ux]
assigned: agent
---

# Context & Objectives

- **Broken Checkout (`POST /payment/checkout` -> HTTP 500):** Upgrading `stripe` to `16.0.0` / `17.0.0` (pinned API `2026-09-30.endive` / `2026-10-28.endive`) removed `payment_method_types` from `POST /v1/checkout/sessions`. `domains/billing/pay.py` still passed `payment_method_types=["card"]`, causing Stripe to reject every Buy Now session with `InvalidRequestError`.
- **Deprecated Stripe SDK Patterns:** Backend modules and scripts relied on legacy global `stripe.api_key`, legacy static resource methods (`stripe.checkout.Session.create`, `stripe.PaymentLink.modify`, `stripe.Refund.create`, etc.), and `stripe.error.*` aliases instead of the supported `StripeClient` `.v1` namespace (`client.v1.*`, `client.construct_event`, top-level `stripe.*Error`).
- **Raw HTTP Error Toasts in Frontend:** Error catch blocks across the Nuxt SPA fell back to `err.message`, surfacing raw `ofetch` `FetchError` strings (e.g. `[POST] "https://api.negolah.my/payment/checkout": 500 Internal Server Error`) or uncaught JS exception strings directly in user-facing toasts and error banners.

# Acceptance Criteria

- [x] `backend/core/stripe_client.py` provides a lazy singleton `get_stripe_client() -> StripeClient` initialized from `core.env.STRIPE_API_KEY`.
- [x] `domains/billing/pay.py::create_checkout_session` calls `get_stripe_client().v1.checkout.sessions.create(params=...)` without `payment_method_types`, using Stripe Dashboard Dynamic Payment Methods.
- [x] All backend Stripe SDK usages (`domains/billing/*`, `domains/negotiation/tools/payment.py`, `scripts/check_fulfillment_anomalies.py`) use `get_stripe_client().v1.*`, `get_stripe_client().construct_event(...)`, and top-level `stripe.*Error` — with zero deprecated global `stripe.api_key`, `stripe.error.*`, static resource calls, or top-level `StripeClient.<service>` calls without `.v1`.
- [x] Backend tests validate every Stripe `params` / `options` payload against `stripe.params.*` TypedDicts and `RequestOptions` and AST-guard against deprecated Stripe syntax.
- [x] `frontend/app/utils/error.ts` exports `DEFAULT_ERROR_MESSAGE`, `isServerError`, and `getErrorMessage` so 5xx/unhandled errors always map to a clear generic message while intentional 4xx `data.detail` strings remain preserved.
- [x] All three locale files (`en.json`, `ms.json`, `zh.json`) define `common.unexpectedError`, and all frontend error toast/banner catch blocks use `getErrorMessage`.

# Technical Design & Contracts

- **Backend `core/stripe_client.py`:** Lazy singleton `get_stripe_client()` returning `stripe.StripeClient(STRIPE_API_KEY or "")`, avoiding global `stripe.api_key` state and safe when `STRIPE_API_KEY` is unset at import time.
- **Stripe `.v1` Calls & Options:**
  - Checkout sessions: `client.v1.checkout.sessions.create(params=...)` (no `payment_method_types`; omit `customer_email` when falsy) and `.retrieve(session_id)`.
  - Payment links, products, prices: `client.v1.products.create/update`, `client.v1.prices.create`, `client.v1.payment_links.create/retrieve/update`.
  - Refunds: `client.v1.refunds.create(params={...}, options={"idempotency_key": ...})` (`idempotency_key` passed in `options: RequestOptions`).
  - Webhooks: `client.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)` with `stripe.SignatureVerificationError`.
- **Frontend `utils/error.ts`:**
  - `isServerError(err)`: checks `err.statusCode`, `err.status`, or `err.response?.status >= 500`.
  - `getErrorMessage(err, fallback = DEFAULT_ERROR_MESSAGE)`: returns `fallback` when `err` is non-object or `isServerError(err)` is true; otherwise returns trimmed `err.data.detail` when it is a non-empty string; otherwise returns `fallback` (never raw `err.message`).

# TDD Scenarios

- [x] **Backend SDK & AST Contract (`tests/test_payment_stripe_compat.py`):** AST scan rejects `stripe.api_key`, `stripe.error.*`, static resource methods, and non-`.v1` client services; runtime payload tests verify `SessionCreateParams`, `PaymentLinkCreateParams`, `PaymentLinkUpdateParams`, `ProductCreateParams`, `ProductUpdateParams`, `PriceCreateParams`, `RefundCreateParams`, and `RequestOptions`.
- [x] **Backend Billing & Negotiation (`tests/test_payment_*.py`, `tests/test_routes_payment.py`, `tests/test_agent_tools_payment.py`):** Checkout session creation omits `payment_method_types`; webhook, payment state cleanup, refunds, and agent checkout links pass using `fake_stripe.v1.*`.
- [x] **Frontend Error Sanitizer (`tests/utils/error.test.ts`):** `ofetch` 500 `FetchError` (`[POST] "...": 500 Internal Server Error`), 502/503/504, network errors, raw JS `Error`s, and 422 arrays all return `fallback`; 4xx `data.detail` strings return trimmed `detail`.
- [x] **Frontend Toast Callers (`tests/pages/*.test.ts`, `tests/components/**/*.test.ts`):** Checkout, chat, auth, profile, and admin error toasts display generic messages on 500 / unhandled errors rather than `POST 500` strings.

# Implementation Files

- `backend/core/stripe_client.py`
- `backend/domains/billing/pay.py`, `routes.py`, `webhooks.py`, `payment_state.py`, `fulfillment.py`, `refunds.py`
- `backend/domains/negotiation/tools/payment.py`
- `backend/scripts/check_fulfillment_anomalies.py`
- `backend/conftest.py` and backend Stripe test suites
- `frontend/app/utils/error.ts`, `frontend/app/locales/{en,ms,zh}.json`
- `frontend/app/composables/useItemAnalysis.ts`
- `frontend/app/components/AppHeader.vue`, `frontend/app/components/admin/Admin*.vue`
- `frontend/app/pages/{items/[id],chat,profile,login,register,forgot-password,reset-password,checkout/success,_console/login}.vue`
- `frontend/tests/utils/error.test.ts` and updated frontend component/page test suites
