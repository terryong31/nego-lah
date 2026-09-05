---
id: SPEC-003
title: Nuxt SPA Migration to Cloudflare Pages & Universal Turnstile
status: complete
priority: high
created: 2026-09-04
tags: [frontend, nuxt, spa, cloudflare-pages, turnstile]
assigned: agent
---

# Context & Objectives
Migrate the Nuxt frontend to a pure Single Page Application (`ssr: false`) that compiles to static assets (`bun run generate`) served from Cloudflare Pages CDN. Integrate Cloudflare Turnstile bot protection globally across the entire application, with explicit token injection on auth endpoints (`login`, `register`, `forgot-password`) and backend mutation requests.

# Acceptance Criteria
- [x] `frontend/nuxt.config.ts` has `ssr: false` configured.
- [x] Static output is generated into `.output/public` via `bun run generate` without SSR runtime errors.
- [x] `@nuxtjs/turnstile` is installed and initialized with `siteKey`.
- [x] A global Turnstile widget/provider is mounted in the root layout with interactive or invisible challenge.
- [x] `useTurnstileToken()` composable provides reactive access to fresh tokens and auto-refresh capability.
- [x] `login.vue`, `register.vue`, and `forgot-password.vue` forward `captchaToken` to Supabase Auth client methods.
- [x] Content Security Policy (CSP) permits `https://challenges.cloudflare.com`.
- [x] Turnstile gates **one-shot submissions only** (the three auth entry points). Authenticated, repeat-call endpoints — notably `POST /chat/stream` — MUST NOT depend on `verify_turnstile`; they rely on JWT auth plus per-user rate limits instead.

# Technical Design & Contracts
- **Turnstile Composable:** `useTurnstileToken()` -> `{ token, isReady, refresh() }`
- **Single-use constraint:** Cloudflare's siteverify accepts a token once and only within
  ~300s; a replay returns `timeout-or-duplicate`. A token therefore cannot cover a stream of
  requests, and no widget is mounted outside the auth pages to mint fresh ones. Adding
  `Depends(verify_turnstile)` to `/chat/stream` 400s every message (`Valid Turnstile
  verification token required`) — masked in tests by conftest pinning `TURNSTILE_SECRET_KEY: ""`,
  which activates the dev bypass.
- **Supabase Auth Integration:**
  ```ts
  supabase.auth.signInWithPassword({
    email,
    password,
    options: { captchaToken: token.value }
  })
  ```

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1:** `useTurnstileToken` initializes with null and updates reactively when token is generated.
- [ ] **Scenario 2:** Auth forms fail submission or display warning if Turnstile token is empty or failed.
- [ ] **Scenario 3:** `bun run generate` generates static HTML/JS/CSS bundle successfully.
- [x] **Scenario 4:** `POST /chat/stream` returns 200 without an `X-Turnstile-Token` header while a non-testing `TURNSTILE_SECRET_KEY` is set (`test_chat_stream_is_not_turnstile_gated`).

# Implementation Files
- `frontend/nuxt.config.ts`
- `frontend/app/composables/useTurnstileToken.ts`
- `frontend/app/pages/login.vue`
- `frontend/app/pages/register.vue`
- `frontend/app/pages/forgot-password.vue`
- `backend/core/security.py` (`verify_turnstile`)
- `backend/tests/test_routes_chat.py` (regression guard)
