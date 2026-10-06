---
id: SPEC-101
title: Non-Functional Audit Remediation (2026-10-06)
status: complete
priority: high
created: 2026-10-07
tags: [security, privacy, reliability, scalability, ci, frontend, backend]
assigned: agent
---

# Context & Objectives
The [2026-10-06 non-functional audit](../audits/2026-10-06-non-functional-audit.md) found live
session cookies in Sentry, a decompression bomb that OOM-kills the API, an admin inbox frozen at
the oldest 1,000 messages, Redis calls that can block forever, a sliding rate-limit window, a
frontend with no CVE gate, and deploys that report green without checking the new image is up.
This spec fixes every finding that is a code or config change in this repo. Findings that need a
console, a plan decision or a larger redesign are listed as out of scope, not silently dropped.

# Acceptance Criteria
- [x] **SEC-1** Sentry events carry no cookies; `Cookie`, `Authorization`, `X-CSRF-Token` are filtered.
- [x] **AVL-1** Images over 50 MP are rejected from the header, before decode; JPEG decodes at reduced size.
- [x] **REL-2** Rate limiting is one atomic fixed-window Lua call; the TTL is set once per window.
- [x] **REL-1** Redis has 2 s socket/connect timeouts; the IP limiter fails open; the default executor is 32 threads; production refuses the in-memory fallback.
- [x] **REL-3** Transient refresh errors (timeout, 5xx) keep the session; a rejected refresh token revokes it.
- [x] **REL-5** Shutdown waits up to 20 s for in-flight agent turns; `stop_grace_period: 30s`.
- [x] **SEC-2** In production a non-JWT bearer token is a 401 with no Supabase call.
- [x] **SEC-6** No handler returns `str(e)`.
- [x] **PRV-3** Account deletion clears the session cookies, blocks the user id for 2 h, and deletes avatars.
- [x] **SCL-1** `GET /admin/chats` reads one row per conversation from `admin_chat_inbox()`, paged.
- [x] **SCL-2** `list_users` is paged everywhere; dashboard counts and totals page past 1,000 rows.
- [x] **OBS-1** `/ready` pings Redis (503 when down); container logs rotate (10 MB × 3); a scheduled workflow monitors `/` and `/ready`.
- [x] **SEC-1 follow-up** `scripts/revoke_all_sessions.py` + a manual, environment-gated workflow rotate every session after the fix ships.
- [x] **PRF-2/MNT-1** The unused asyncpg pool, slowapi wiring and `three` are removed.
- [x] **DEP-1** Deploys pin the commit SHA, reload Caddy gracefully, wait for health, and roll back on failure.
- [x] **DEP-2** Top-level `permissions: contents: read`; third-party actions pinned by SHA; bandit runs in CI.
- [x] **SUP-1** CI runs `bun audit --audit-level=high` with justified ignores; devtools is opt-in; Nuxt 4.5 (Vite 8, test-utils 4.3) and in-range advisories fixed.
- [x] **PRV-1/PRV-2** Replay records no network bodies; ad consent defaults to denied; page views send `path`.
- [x] **SEC-4** One CSP source (`build/csp.ts`); production drops Supabase and localhost.
- [x] **A11Y-1/2** Light-mode primary is green-700 (5.1:1); the item gallery image has `alt`.
- [x] **SEO-1** Canonical and `og:url` are per route; item pages set their own title, description and image.

# Technical Design & Contracts
- `supabase/migrations/20261007000000_admin_chat_inbox.sql`: `admin_chat_inbox()` → `(user_id,
  message_count, last_content (≤100 chars), last_role, last_source, last_activity, last_human_at)`,
  `SECURITY INVOKER`, execute granted to `service_role` only. Applied by CI before the backend deploys.
- `core/pagination.fetch_all(build_query)` pages any ordered PostgREST query with `.range()`.
- `IdentityService.list_all_users(client)` pages GoTrue at 1,000/page.
- `core.cache.FIXED_WINDOW_SCRIPT`: `INCR`; `EXPIRE` only when `TTL < 0`. Allowed iff count ≤ max.
- `GET /ready` → `{status, redis, notifications_distributed}`; 200 or 503. Exempt from the IP limiter.
- Compose image: `ghcr.io/…/nego-lah-backend:${BACKEND_IMAGE_TAG:-latest}`.

# TDD Scenarios
- [x] A captured Sentry event has no `cookies` and filtered credential headers (`test_telemetry.py`).
- [x] A 101×100 PNG over a 100×100 cap is a 400 and `load()` is never called (`test_core_images.py`).
- [x] 14 requests 7 s apart at 10/60 s are all allowed; the check is one `eval` (`test_cache.py`).
- [x] Redis client gets timeouts; production raises instead of falling back (`test_cache.py`).
- [x] A Redis error in the IP limiter still returns 200 (`test_ip_rate_limit_middleware.py`).
- [x] Transient refresh errors keep the session; a 400 revokes (`test_user_session.py`).
- [x] Lifespan sizes the executor and lets a running turn finish (`test_main.py`).
- [x] `/ready` is 200 with Redis, 503 without (`test_main.py`).
- [x] Inbox and `fetch_all` page until a short page; inbox failure is a 503, not an empty list.
- [x] `list_all_users` walks three pages (`test_domain_services.py`).
- [x] Workflow: read-only token, SHA-pinned actions, bandit, `bun audit`, SHA deploy + health gate (`test_ci_workflow.py`).
- [x] `_headers` CSP equals `contentSecurityPolicy({ dev: false })` (`security-headers.test.ts`).
- [x] Under Nuxt 4.5 `$fetch` is an auto-import: composable tests mock it with `mockNuxtImport`.
- [x] Canonical is the current route (`app.test.ts`); consent and replay defaults (`analytics.test.ts`).

# Out of scope (tracked in the audit)
SEC-3 (Lightsail firewall, console), SEC-5 (moving live session cookies to host-only needs a
two-cookie migration), SEC-7, PRV-4, REL-4 (lease renewal), PRF-1 (blocking-call CI scan), PRF-3
lazy locales/Replay, CST-1 (charge real token usage — needs usage plumbed out of `bot.py`),
OBS-1 request IDs and metrics, OBS-2, DR-1, DEP-2 production-environment reviewer (repo settings),
DEP-3, MNT-2, TST-1/2, A11Y-2 `/login` `<h1>` (UAuthForm renders its title as a `div`), and
archive purge of deleted users' pre-2026-09 transcripts.

# Implementation Files
- `backend/core/{telemetry,images,cache,env,rate_limit_middleware,limiter,pagination}.py`, `backend/main.py`
- `backend/domains/identity/{auth_middleware,user_session,routes,services,admin_users}.py`
- `backend/domains/negotiation/{admin_routes,memory,routes,services}.py`, `billing/{admin_routes,services}.py`, `catalog/services.py`, `console/admin_listings.py`
- `supabase/migrations/20261007000000_admin_chat_inbox.sql`, `docker-compose.yml`, `.github/workflows/deploy.yml`
- `frontend/{nuxt.config.ts,sentry.client.config.ts,build/csp.ts,public/_headers,scripts/audit.sh,package.json}`
- `frontend/app/{app.vue,pages/items/[id].vue,plugins/analytics.client.ts,assets/css/main.css}`
