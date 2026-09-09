# 12. Transactional Email — Sender Mailbox and Failure Alerting

- Status: Accepted
- Date: 2026-09-09
- Deciders: Terry (owner), AI Agent
- Relates to: SPEC-048 (TODO #38); builds on SPEC-007 (admin OTP delivery), SPEC-021 (modular email templates), SPEC-039 (email design)

## Context

A report that buyers weren't receiving purchase receipts. Investigation
(`scripts/diagnose_resend.py` + Sentry, prod, 2026-09-09) found the pipeline
**working** — `negolah.my` verified in Resend, a real buyer receipt delivered
end-to-end on 2026-09-08, no errors in the path — but with two latent
weaknesses and one misconfiguration:

1. The receipt went only to `session.customer_details.email` (what the buyer
   typed on Stripe). No pre-fill, no fallback — so a blank or mistyped Stripe
   email meant no receipt, and the buyer's actual account email was never used.
2. A failed or skipped send was a `logger.warning` — invisible in practice.
3. `RESEND_FORWARD_FROM` was `relay@negolah.my` — the mailbox the **inbound**
   support relay (SPEC-007 follow-on) receives at, reused as the **outbound**
   sender for every transactional email.

## Decision

1. **Recipient resolution:** the receipt goes to
   `stripe_customer_email or account_email(user_id)`. The checkout session
   pre-fills Stripe's `customer_email` from the authenticated account
   (SPEC-047), so the Stripe value is normally already the account address; the
   direct Supabase-auth lookup (`payment/buyer.py::account_email`) is the
   fallback. One helper, shared by the checkout and fulfilment paths.

2. **Failure is loud.** When `send_purchase_receipt` returns `False` (Resend
   rejected every sender) or no address resolves, `_finalize_won_sale` calls
   `sentry_sdk.capture_message(level="error", tags={"alert": "receipt_undelivered"
   | "receipt_no_address", "order_id": …})` in addition to the error log.
   Fulfilment itself still succeeds — a receipt is not worth failing a paid
   order over — but the miss is now an alert.

3. **Dedicated sender mailbox.** `RESEND_FORWARD_FROM` is
   `Nego-Lah <receipts@negolah.my>` — set in Infisical `/Backend` (dev + prod)
   on 2026-09-09. The verified `negolah.my` domain already authorises it; no DNS
   change. The old value (`relay@negolah.my`, the inbound support-relay mailbox)
   is out of the `From:` line so bounce handling, reply routing and domain
   reputation aren't entangled. Caveat: this one var is also the `From:` for the
   admin OTP fallback send and for the inbound relay's own forwarding (the relay
   sets `reply_to` = original sender, so replies are unaffected). If those need
   distinct identities, add `RESEND_RELAY_FROM` / `RESEND_AUTH_FROM` rather than
   reverting.

## Consequences

- **Positive:** A receipt now has two chances at a good address, and a genuine
  delivery failure pages instead of scrolling past. The sender mailbox matches
  its purpose.
- **Negative:** `_finalize_won_sale` does one more Supabase-auth call on the
  fallback path (webhook context, not user-blocking). Acceptable.
- **Neutral:** No template change — SPEC-039's receipt design is untouched.
- **Operator step (done 2026-09-09):** the `RESEND_FORWARD_FROM` value change is
  not in code (secrets live in Infisical) — applied to dev + prod `/Backend` via
  `infisical secrets set`.
- **Follow-on:** if `receipt_undelivered` ever fires, extend to the Redis-backed
  retry queue sketched in SPEC-048's rejected "retry" option.
