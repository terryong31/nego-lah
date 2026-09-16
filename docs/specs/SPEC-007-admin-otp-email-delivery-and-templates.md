---
id: SPEC-007
title: Admin OTP Email Delivery & Branded HTML Templates
status: complete
priority: high
created: 2026-09-04
tags: [auth, admin, email, supabase]
assigned: agent
---

# Context & Objectives
During admin authentication at `/_console/login`, the backend calls Supabase's `sign_in_with_otp` to deliver an 8-digit OTP code to the admin email. Supabase failed to deliver the email with `AuthApiError: Error sending magic link email`, resulting in Sentry error logs at `admin_session.py:145`.
Supabase log inspection revealed the root cause: custom SMTP is routed through Resend (`smtp.resend.com`), which returned `550: "The negolah.my domain is not verified. Please, add and verify your domain on https://resend.com/domains"`.
Furthermore, Supabase's default email template does not render an OTP code box (`{{ .Token }}`) or branded HTML markup.

This spec establishes:
1. Production-ready, responsive, brand-aligned HTML email templates for Nego-lah (`magic_link.html`, `recovery.html`, `confirmation.html`).
2. Supabase CLI configuration linking these templates via `supabase/config.toml`.
3. Clear guidance for Supabase Dashboard and Resend domain configuration.
4. Resilient backend OTP delivery fallback in `backend/admin_session.py` via `admin_supabase.auth.admin.generate_link()` and direct Resend API dispatch.

# Acceptance Criteria
- [ ] Branded, responsive HTML template created at `supabase/templates/magic_link.html` displaying the OTP code `{{ .Token }}` prominently with fallback magic link `{{ .ConfirmationURL }}`.
- [ ] Branded HTML templates created for `supabase/templates/recovery.html` and `supabase/templates/confirmation.html`.
- [ ] `supabase/config.toml` updated with `[auth.email.template.*]` pointing to local HTML files.
- [ ] `backend/admin_session.py` enhanced with resilient OTP dispatch: if Supabase's internal SMTP fails or in resilient mode, generates link via service-role `generate_link()` and dispatches via Resend API (with `onboarding@resend.dev` development fallback if custom domain is unverified).
- [ ] All automated tests pass: `test_admin_session.py` coverage for OTP dispatch fallback, and full pytest suite remains 100% green.

# Technical Design & Contracts
- **Supabase Template Variables**:
  - `{{ .Token }}`: 6-8 digit OTP code.
  - `{{ .ConfirmationURL }}`: Direct verification URL.
  - `{{ .SiteURL }}`: Application base URL (`https://negolah.my` or `http://localhost:3000`).
- **Resend Dispatch Contract**:
  - Endpoint: `https://api.resend.com/emails`
  - Payload: `{ "from": from_addr, "to": email, "subject": "...", "html": html_content }`
  - Fallback sender: If sending via `relay@negolah.my` fails with 403/550 unverified domain or during dev, fallback to `onboarding@resend.dev` for account owner delivery.

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1:** `password_then_send_otp` succeeds normally when `sign_in_with_otp` succeeds.
- [ ] **Scenario 2:** When `sign_in_with_otp` fails (e.g. Supabase SMTP failure), `password_then_send_otp` falls back to `generate_link` + Resend dispatch, logging an info/warning rather than completely dropping the OTP.

# Implementation Files
- `supabase/templates/magic_link.html` - Branded HTML template for Admin 2FA OTP / Magic Link.
- `supabase/templates/recovery.html` - Branded HTML template for Password Reset.
- `supabase/templates/confirmation.html` - Branded HTML template for Account Confirmation.
- `supabase/config.toml` - Supabase email template configuration.
- `backend/admin_session.py` - Resilient OTP generation & delivery fallback.
- `backend/tests/test_admin_session.py` - Unit tests for OTP delivery fallback.
