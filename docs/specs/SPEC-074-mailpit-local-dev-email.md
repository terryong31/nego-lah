---
id: SPEC-074
title: Mailpit Local Dev Email + Dev Resend Retirement Plan
status: complete
priority: medium
created: 2026-09-12
tags: [email, developer-experience, infrastructure]
assigned: agent
---

# Context & Objectives
Outbound dev email currently goes through the real Resend API. The sandbox
sender (`onboarding@resend.dev`) only delivers to the account owner's inbox,
silently drops everyone else, and every debug cycle burns API quota and risks
touching real inboxes. Mailpit is a local SMTP sink with a web UI: catch-all,
instant, zero external calls.

Objectives:
1. Local dev email routes to Mailpit over plain SMTP. The production Resend
   path stays byte-for-byte untouched.
2. Record the plan to retire Resend from the dev environment entirely (Resend
   remains the production sender and the inbound-forwarding provider).

# Acceptance Criteria
- [x] Setting `SMTP_HOST` switches the email funnel to SMTP; leaving it unset
      keeps Resend (the production default) unchanged.
- [x] Every `email_service` sender (receipt, sale alert, unread digest,
      shipment notice, human transfer alert) routes through the dispatcher.
- [x] An SMTP send failure returns `False` and logs a warning — it never
      raises into the request path.
- [x] `mise run dev:mailpit` starts Mailpit (SMTP :1025, web UI :8025)
      idempotently; `mise run dev:all` includes it.
- [x] The test suite stays hermetic: SMTP is disabled in tests even when a
      developer's `backend/.env` sets `SMTP_HOST`.
- [x] `docker-compose.yml` (production stack) gains no Mailpit service and no
      `SMTP_*` env vars.

# Technical Design & Contracts
- `env.py`: `SMTP_HOST` (unset in prod), `SMTP_PORT` (default 1025), and
  `SMTP_FROM` (sender display address; falls back to `RESEND_FORWARD_FROM`,
  then `Nego-Lah <noreply@negolah.my>`).
- `email_service`: new `_send_email(to, subject, html)` dispatcher — SMTP when
  `SMTP_HOST` is set, else the existing `_send_email_via_resend` (unchanged).
  SMTP delivery uses stdlib `smtplib` + `EmailMessage` with an HTML part and a
  10s timeout. No new dependency.
- Transport precedence: `SMTP_HOST` beats `RESEND_API_KEY`, so a dev machine
  that still carries the Resend key from Infisical cannot silently keep
  sending real mail.
- Mailpit runs as a local Docker container (`nego-lah-mailpit`) managed by a
  mise task — deliberately NOT in the prod `docker-compose.yml`.

# Dev Resend Retirement (Phase 2 — executed 2026-09-12)
- [x] `RESEND_API_KEY` deleted from the Infisical dev `/Backend` env
      (`infisical secrets delete --type shared` — it is a shared secret, and
      the default personal-type delete 404s) and from the local gitignored
      `backend/.env`, which `load_dotenv` was silently refilling after the
      Infisical removal.
- [x] Multi-sender fallback loop removed from `_send_email_via_resend`;
      Resend now sends from the single verified `RESEND_FORWARD_FROM` sender
      and fails closed when it is unset (prod keeps
      `Nego-Lah <receipts@negolah.my>`).
- [x] The admin OTP fallback (`admin_session.py`) no longer calls the Resend
      API with its own sandbox sender loop — it renders its template and hands
      off to the shared funnel via `send_email_raw` (Mailpit in dev).
- [x] Fulfillment's sandbox redirect of receipts to `RESEND_FORWARD_TO`
      (Stripe test-key mode) removed — receipts are addressed to the resolved
      buyer in every environment.
- [x] `mise run email:diagnose` (dev variant) retired; `email:diagnose:prod`
      kept on Resend.
- [x] Stale `RESEND_TEST_OVERRIDE_TO` comment removed.
- [x] `ADMIN_NOTIFY_EMAIL` introduced (falls back to `RESEND_FORWARD_TO`) as
      the admin alert inbox; sale alerts and human-handoff alerts target it.
- Resend remains in production for sending and inbound webhook forwarding
  (`routes/webhooks.py`) — explicitly out of scope and untouched.

# Test-Driven Development (TDD) Scenarios
- [x] **SMTP routing:** with `SMTP_HOST` set, `send_purchase_receipt` delivers
      via `smtplib.SMTP.send_message` and never constructs `httpx.Client`.
- [x] **Message shape:** From (fallback chain), To, Subject, and the rendered
      HTML body all land on the `EmailMessage`.
- [x] **Graceful failure:** an `smtplib` exception returns `False`.
- [x] **Resend regression guard:** with `SMTP_HOST` unset, sends still hit the
      Resend HTTP path.
- [x] **Suite hermeticity:** conftest pins `SMTP_HOST=""` so the Resend suite
      passes regardless of the developer's local `.env`.
- [x] **Single verified sender:** the Resend payload `from` is
      `RESEND_FORWARD_FROM`; without it, no send is attempted at all.
- [x] **Admin alert target:** sale alerts and handoff alerts go to
      `ADMIN_NOTIFY_EMAIL`.
- [x] **OTP funnel:** the admin OTP fallback delegates to `send_email_raw`
      instead of calling the Resend API itself.
- [x] **No sandbox redirect:** on a Stripe test key the receipt is addressed
      to the resolved buyer email, not the admin catch-all.

# Implementation Files
- `backend/env.py` - `SMTP_HOST` / `SMTP_PORT` / `SMTP_FROM`; `ADMIN_NOTIFY_EMAIL`
- `backend/services/email_service.py` - `_send_email` dispatcher, `_send_email_via_smtp`,
  `send_email_raw`, single-sender Resend path
- `backend/admin_session.py` - OTP fallback routed through the shared funnel
- `backend/payment/fulfillment.py` - sandbox receipt redirect removed
- `backend/tests/test_email_service.py` - SMTP + Phase 2 scenarios
- `backend/tests/test_admin_session.py` - OTP funnel scenarios
- `backend/tests/test_payment_fulfillment.py` - no-sandbox-redirect scenario
- `backend/conftest.py` - `SMTP_HOST=""` in `_TEST_ENV`
- `mise.toml` - `dev:mailpit` task; added to `dev:all`; dev `email:diagnose` retired
- `backend/.env.example` - local email section
