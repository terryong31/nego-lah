---
id: SPEC-022
title: Environment-Conditional Sentry Telemetry and Cloudflare Turnstile Verification
status: completed
priority: high
created: 2026-09-05
tags: [frontend, backend, sentry, turnstile, security, telemetry, sentry-cli]
assigned: agent
---

# Context & Objectives
Development environments should not spam Sentry with error events, session replays, or profile chunks, nor should local development and testing be obstructed or slowed down by Cloudflare Turnstile captcha challenges. In production, however, Sentry error monitoring and Turnstile bot protection are critical security and operational requirements that must be strictly enforced.

Additionally, `sentry-cli` must be integrated into the monorepo workflow to verify projects, inspect releases, and validate telemetry configurations.

# Acceptance Criteria
### Sentry Telemetry
- [x] **Backend Development:** In development mode (`ENV` != `production`), Sentry telemetry is completely disabled even if `SENTRY_DSN` is present in local `.env`. No network calls or profiling to Sentry occur.
- [x] **Backend Production:** In production mode (`ENV` == `production` or `prod`), Sentry is strictly enforced. If `SENTRY_DSN` is missing or empty, application initialization raises a `RuntimeError`.
- [x] **Frontend Development:** In development mode (`NODE_ENV` != `production`), `@sentry/nuxt` initialization is disabled (`enabled: false`), and `sentry.client.config.ts` / `sentry.server.config.ts` skip initialization.
- [x] **Frontend Production:** In production mode, Sentry client initialization is active with sample rates and session replays enabled; missing DSN raises an error.
- [x] **Sentry CLI Tooling:** Sentry CLI is configured via `.sentryclirc` and `mise.toml` tasks (`mise run sentry:info`, `mise run sentry:releases`) using `nego-lah` org and `nego-lah-frontend` / `nego-lah-backend` projects.

### Cloudflare Turnstile Protection
- [x] **Backend Development:** In development mode, `verify_turnstile` automatically returns `True` without requiring headers, checking keys, or calling Cloudflare siteverify.
- [x] **Backend Production:** In production mode, `verify_turnstile` strictly enforces:
  1. `TURNSTILE_SECRET_KEY` must be configured (missing key raises HTTP 500).
  2. Dummy or test tokens (`dummy-token`, `test-token`, `XXXX.DUMMY.*`) and test keys (`1x00000000...`) are rejected with HTTP 403.
  3. A valid token (`X-Turnstile-Token` or `cf-turnstile-response`) is mandatory (missing raises HTTP 400).
  4. Cloudflare siteverify API response must be `success: true` (failure raises HTTP 403).
- [x] **Frontend Development:** In development mode, `useTurnstileToken().isEnabled` is `false`, and the `<NuxtTurnstile>` widget is not rendered on auth pages (`login.vue`, `register.vue`, `forgot-password.vue`). Auth submissions proceed without captcha token.
- [x] **Frontend Production:** In production mode, `useTurnstileToken().isEnabled` is `true`, `<NuxtTurnstile>` widget renders, and auth forms block submission with a toast notification if the Turnstile challenge is not completed.

# Test Scenarios
- [x] **Scenario 1 (Backend Sentry Dev vs Prod):**
  - Dev mode with DSN -> `sentry_sdk.init` NOT called.
  - Prod mode with DSN -> `sentry_sdk.init` called with `environment="production"`.
  - Prod mode without DSN -> raises `RuntimeError`.
- [x] **Scenario 2 (Backend Turnstile Dev vs Prod):**
  - Dev mode without token -> returns `True`.
  - Prod mode without secret key -> raises HTTP 500.
  - Prod mode with missing token -> raises HTTP 400.
  - Prod mode with test/dummy token -> raises HTTP 403.
  - Prod mode with valid token -> verifies against Cloudflare siteverify.
- [x] **Scenario 3 (Frontend Turnstile Composable & UI):**
  - `useTurnstileToken().isEnabled` reflects dev vs prod config.
  - Auth pages conditionally render `<NuxtTurnstile>` only when enabled.
  - Submissions in prod enforce token presence.
- [x] **Scenario 4 (Sentry CLI Verification):**
  - `sentry-cli info` and `sentry-cli releases list` succeed and report the active projects.

# Implementation Files
- `specs/SPEC-022-env-conditional-sentry-and-turnstile.md`
- `.sentryclirc`
- `mise.toml`
- `backend/core/telemetry.py`
- `backend/core/security.py`
- `backend/main.py`
- `backend/tests/test_main.py`
- `backend/tests/test_security_turnstile.py`
- `frontend/nuxt.config.ts`
- `frontend/sentry.client.config.ts`
- `frontend/sentry.server.config.ts`
- `frontend/app/composables/useTurnstileToken.ts`
- `frontend/app/pages/login.vue`
- `frontend/app/pages/register.vue`
- `frontend/app/pages/forgot-password.vue`
- `frontend/app/locales/{en,ms,zh}.json`
- `frontend/tests/composables/useTurnstileToken.test.ts`
