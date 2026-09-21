---
id: SPEC-093
title: Server-Side Sessions — httpOnly Cookies for the Buyer App
status: in-progress
priority: high
created: 2026-09-18
tags: [security, identity, auth, frontend, compliance]
assigned: agent
---

# Context & Objectives

`@nuxtjs/supabase` keeps the buyer's Supabase session in `localStorage`, and every caller
reads it back out: `useApi` attaches `Bearer ${session.access_token}`, `chat.vue` passes the
same token to `DefaultChatTransport`, `useNotifications` mints an SSE ticket with it. Any
script that executes in the page origin can read that token and replay it for its full hour
against `api.negolah.my` — a session hijack that survives the tab closing, with nothing on
the server able to tell the replay from the buyer.

The admin console already does this correctly (SPEC-018): an opaque session id in Redis,
returned as an httpOnly Secure cookie, with a double-submit CSRF token. Nothing for the
buyer is missing that pattern for a technical reason — the SPA makes **no** Supabase data or
storage calls; it uses supabase-js for auth and one realtime channel, and every byte of data
already travels through FastAPI. The buyer side simply predates the admin work.

**Objective:** the buyer's credentials never reach JavaScript. The browser holds an opaque
session id it cannot read; FastAPI holds the Supabase tokens.

Not claimed: GDPR Art. 32 and PDPA's Security Principle require "appropriate technical
measures", not httpOnly specifically. But a bearer token readable by script is the finding
every pentest and DPIA raises, and it is the one blocking answer in an EU/US buyer's
security questionnaire.

# Acceptance Criteria

- [x] **No token in script reach:** after sign-in, `localStorage`, `sessionStorage` and
      `document.cookie` contain no access or refresh token. Grepping the bundle for
      `getSession()` on a buyer path returns nothing.
- [x] **Backend owns the exchange:** password, OAuth (PKCE), signup confirm, password reset
      and email change all complete server-side; the browser only ever sees a 302 and a cookie.
- [x] **Opaque id, instant revocation:** the cookie is a random sid; deleting the Redis key
      ends the session on the next request, as it does for admin.
- [x] **CSRF closed:** every mutating buyer endpoint enforces `verify_csrf_token`. Stripe and
      Resend webhooks stay exempt (signature-authenticated, no cookie).
- [x] **Silent refresh:** an expiring access token is refreshed server-side, single-flight, so
      concurrent tabs cannot race the rotation into a logout.
- [x] **Bearer still accepted** for the eval harness and tests, behind one resolver.
- [ ] **No functional regression:** login, Google OAuth, register + confirm, forgot/reset
      password, chat stream, SSE notifications, checkout return and logout all still work.
      *Covered by unit tests on both sides; NOT yet exercised against live Supabase.
      Needs a manual pass, and `supabase config push` first — the API callback has to be
      in `additional_redirect_urls` or every auth link is refused.*
- [x] Backend coverage stays ≥88% (90.12%).

# Technical Design & Contracts

```
POST   /auth/login            {email,password}  -> sets sb_sid + csrf_token, 200 {user}
POST   /auth/register         {email,password}  -> 200 {confirmation_sent}
GET    /auth/oauth/start?provider=google        -> 302 Supabase authorize (PKCE verifier in Redis)
GET    /auth/callback?code=|token_hash=         -> exchange, set cookies, 302 FRONTEND_URL
GET    /auth/session                            -> 200 {user} | 401
POST   /auth/logout                             -> clears cookies + Redis
POST   /auth/password/forgot | /auth/password/reset
```

Redis `user:sess:{sid}` -> `{user_id, access_token, refresh_token, exp}`, TTL 30d sliding.
Cookie `sb_sid`: httpOnly, Secure, **SameSite=Lax**, `domain=.negolah.my`, path `/`.

*Lax, not Strict:* the Stripe return to `/checkout/success` and every Supabase email link are
top-level cross-site GETs. Strict drops the cookie on exactly those, which reads as a logout.

`verify_user_token` resolves in order: `sb_sid` cookie -> Redis -> (refresh if `exp` within
60s, under a `SET NX` lock with a grace window on the old refresh token) -> `user_id`;
falls back to the `Authorization` header. The ban check is unchanged.

`core/csrf.py` is generalized over (cookie name, Redis prefix) so admin and buyer share it.

Redis holds the sessions, so its limits are now auth's limits. Local dev runs the sidecar
(192 MB, `volatile-ttl`, evicts shortest-TTL-first — sessions take the longest TTL, so they go
last). Prod runs managed Redis (64 MB, `noeviction`), where nothing evicts and `SETEX` fails at
the cap instead: existing sessions keep working, new logins stop. ADR-0028 has the numbers.

# TDD Scenarios

- [x] **S1:** `POST /auth/login` sets an httpOnly `sb_sid`; the body carries no token.
- [x] **S2:** a request with a valid `sb_sid` resolves to the right `user_id`.
- [x] **S3:** a mutating buyer call with a cookie but no `X-CSRF-Token` -> 403.
- [x] **S4:** `DELETE` of the Redis session key -> the next request 401s.
- [x] **S5:** a session whose access token has expired is refreshed once under concurrency
      (N parallel requests, one refresh call, no logout).
- [x] **S6:** `Authorization: Bearer` still authenticates (harness path).
- [x] **S7:** `POST /payment/webhook/stripe` is unaffected by CSRF.
- [x] **S8:** OAuth callback with a mismatched `state` -> 400, no cookie set.
- [x] **S9 (frontend):** `useApi` sends `credentials: 'include'` + the CSRF header and never
      calls `supabase.auth`.
- [x] **S10 (frontend):** a 401 clears local user state and bounces to `/login` as today.

# Implementation Files

- `backend/domains/identity/user_session.py` — session store, refresh, cookie lifecycle
- `backend/domains/identity/auth_routes.py` — the routes above
- `backend/domains/identity/auth_middleware.py` — cookie-first resolver
- `backend/core/csrf.py` — generalized over session kind
- `backend/domains/{negotiation,billing,identity}/routes.py` — `verify_csrf_token` deps
- `frontend/app/composables/useAuth.ts` — replaces `useSupabaseUser`/`useSupabaseClient`
- `frontend/app/plugins/auth.client.ts` — resolves the session before the first route guard
- `frontend/app/composables/useApi.ts`, `useNotifications.ts` — credentialed fetch
- `frontend/app/pages/{login,register,confirm,forgot-password,reset-password,profile}.vue`
- `frontend/app/middleware/auth.ts`, `app/plugins/item-store-identity.client.ts`
- `frontend/nuxt.config.ts` — drop `@nuxtjs/supabase`
- `supabase/templates/*` — redirect targets move to the API callback
