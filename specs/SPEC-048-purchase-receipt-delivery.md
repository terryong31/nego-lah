---
id: SPEC-048
title: Purchase-Receipt Email Delivery — Diagnosis & Hardening
status: complete
priority: high
created: 2026-09-09
tags: [backend, payment, email, observability]
assigned: agent
---

# Context & Objectives

Report: "user still does not receive email upon payment successful" (TODO #38).

## Investigation (Sentry + Resend, prod, 2026-09-09)

`backend/scripts/diagnose_resend.py` (new, read-only) + the Sentry API were run
against prod secrets. Findings:

- **The receipt pipeline works.** `negolah.my` is **verified** in Resend
  (`ap-northeast-1`). Resend's log shows a real buyer receipt delivered
  end-to-end: `2026-09-08 09:00 → wyjoec83@gmail.com "Receipt for your purchase:
  Acer PM161Q…" status=delivered`, paired with the seller's "Item Sold" alert.
- **No Sentry errors in the receipt path** in the last 14 days. The
  `StripeObject is not a dict` 500s were on `/payment/confirm-payment`, last seen
  2026-09-05, already fixed by `payment/stripe_compat.stripe_get`. The
  `'NoneType'.get` errors are in `routes.webhooks.resend_webhook` (the *inbound*
  relay), unrelated.

## Root-cause candidates that remain (and what this spec does about them)

1. **Wrong address.** The receipt is sent to `session.customer_details.email` —
   whatever the buyer typed on the Stripe page — which can be blank, a typo, or
   simply different from their Nego-Lah account email. → **Fix in code:**
   `/payment/checkout` pre-fills Stripe's `customer_email` from the buyer's
   account (SPEC-047), and `_finalize_won_sale` falls back to a direct account
   lookup when Stripe passed none.
2. **Silent failure.** When no address resolved, or Resend rejected every send,
   the old code only wrote `logger.warning` — invisible. → **Fix in code:** fire
   `sentry_sdk.capture_message(level="error", tags={"alert": …})` so the *next*
   occurrence is a real alert, not a needle in the log stream.
3. **`RESEND_FORWARD_FROM = relay@negolah.my`** reused the **inbound relay
   mailbox** as the outbound sender. It works (domain verified) but is the wrong
   mailbox and hurts deliverability/reputation over time. → **Done 2026-09-09:**
   `RESEND_FORWARD_FROM = "Nego-Lah <receipts@negolah.my>"` set in Infisical
   `/Backend` for `dev` + `prod` via `infisical secrets set`; `negolah.my` is
   verified (`ap-northeast-1`), no DNS change. Note the one var is shared by the
   transactional sender, the admin OTP fallback, and the inbound relay `From:`
   (relay keeps `reply_to` = original sender, so replies still route) — split
   into `RESEND_RELAY_FROM` later if those should diverge.

# Acceptance Criteria

- [x] `backend/scripts/diagnose_resend.py` exists, is read-only, and prints env
      (masked) + Resend domain verification status + recent send events. Wired as
      `mise run email:diagnose` (dev) / `email:diagnose:prod`.
- [x] `_finalize_won_sale` resolves the recipient as
      `buyer_email (Stripe) or account_email(user_id)` — the account lookup is
      the fallback, `payment/buyer.py::account_email` (shared with SPEC-047's
      checkout pre-fill).
- [x] When `send_purchase_receipt(...)` returns `False`, `_finalize_won_sale`
      logs an error **and** `sentry_sdk.capture_message(level="error",
      tags={"alert": "receipt_undelivered", "order_id": …})`.
- [x] When no recipient address resolves at all, same: error log +
      `capture_message(..., tags={"alert": "receipt_no_address", …})`.
- [x] The seller "Item Sold" alert path is unchanged.
- [x] `docs/adr/0012-transactional-email-sender-and-alerting.md` records the
      sender-mailbox decision and the alert-on-failure policy.

# Test-Driven Development (TDD) Scenarios

- [x] **#38-1:** `send_purchase_receipt` returns `False` → `_finalize_won_sale`
      calls `sentry_sdk.capture_message` once with `level="error"` and
      `tags["alert"] == "receipt_undelivered"`; fulfilment still returns success.
- [x] **#38-2:** no `buyer_email` and `account_email` returns `None` → receipt is
      not attempted, `capture_message` fires with
      `tags["alert"] == "receipt_no_address"`.
- [x] **#38-3:** `buyer_email` present + `send_purchase_receipt` returns truthy →
      no `capture_message`, receipt sent to that address.
- [x] **#38-4:** `buyer_email` absent but `account_email(user_id)` returns an
      address → receipt sent to the account address.
- [x] **#38-5 (script):** `diagnose_resend.py` runs without network as a unit —
      `main()` returns 1 and prints the guidance line when `RESEND_API_KEY` is
      unset. (Full run is manual, through `infisical run`.)

# Implementation Files

- `specs/SPEC-048-purchase-receipt-delivery.md` — this spec
- `docs/adr/0012-transactional-email-sender-and-alerting.md` — decision record
- `backend/scripts/diagnose_resend.py` — read-only Resend/env diagnostic (new)
- `backend/payment/buyer.py` — `account_email` (new; shared with SPEC-047)
- `backend/payment/fulfillment.py` — account-email fallback + Sentry alert on failure
- `mise.toml` — `email:diagnose`, `email:diagnose:prod` tasks
- `backend/tests/test_payment_fulfillment.py` — receipt alerting scenarios
- `backend/tests/test_scripts_diagnose_resend.py` — script guard (new)
