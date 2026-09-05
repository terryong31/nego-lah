---
id: SPEC-023
title: Non-Blocking Request Path — Auth Dependency, Storefront and Stripe Webhook
status: complete
priority: high
created: 2026-09-05
tags: [backend, concurrency, performance, asyncio, auth]
assigned: agent
---

# Context & Objectives
SPEC-018 took the synchronous Supabase/Realtime calls out of the chat handlers' event loop. The same pattern remains on the rest of the request path, and one instance of it is worse than anything fixed there:

1. **`verify_user_token` is an `async def` FastAPI dependency.** FastAPI runs `def` *endpoints* in a threadpool but always runs `async def` *dependencies* on the event loop — so the synchronous `admin_supabase.auth.get_user()` (on a token-cache miss) and the ban lookup (on a ban-cache miss) stall **every** in-flight request on that worker, for every authenticated endpoint in the API. This is the single hottest blocking call in the codebase.
2. **`routes/items.py`** — the public storefront, the highest-traffic surface — runs all three handlers as `async def` while calling synchronous Supabase reads plus per-item Redis discount lookups directly on the loop.
3. **`routes/payment.py::stripe_webhook`** is `async def` and runs `handle_checkout_completed` inline: Supabase writes, an email send, and potentially a Stripe refund. Stripe retries on timeout, so a stalled loop here compounds.

The rest of `routes/payment.py`, `routes/admin.py` and `routes/user.py` already declare their blocking handlers as `def`, which FastAPI offloads for us — those are correct as they stand.

Objective: no synchronous network I/O executes on the event loop anywhere in the request path.

# Acceptance Criteria
- [x] A token-cache miss in `verify_user_token` does not block the event loop; concurrent requests keep progressing during the Supabase round trip.
- [x] The ban-status lookup is likewise off-loop.
- [x] `get_optional_user_id` (storefront personalisation) is off-loop on a cache miss.
- [x] All three `routes/items.py` handlers do their Supabase reads and discount decoration off-loop.
- [x] `stripe_webhook` verifies and fulfils off-loop.
- [x] Behaviour is unchanged: same responses, same status codes, same error mapping.
- [x] The avatar/profile upload handlers (`routes/user.py::update_profile`, `routes/admin.py::upload_user_avatar`) and the admin item/market handlers likewise keep their synchronous storage and scraping calls off the loop.

# Technical Design & Contracts
`asyncio.to_thread(...)` around each synchronous call, matching the idiom already used in `main.py`'s cleanup loop and the chat routes. No endpoint signatures change.

For list endpoints the whole read-plus-decorate step moves into a single thread hop rather than one per item, so a 20-item page costs one context switch instead of forty Redis round trips on the loop.

Anti-pattern to avoid: making these handlers `def` instead. It works for endpoints but not for dependencies, and it would fragment the codebase's async style — `to_thread` keeps one rule: synchronous I/O always goes through a thread.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** With a 200ms synchronous `auth.get_user`, a ticker coroutine keeps advancing while `verify_user_token` resolves (0 ticks means the loop was blocked).
- [x] **Scenario 2:** Same for `get_optional_user_id`, and for a slow ban lookup.
- [x] **Scenario 3:** `GET /items`, `/items/featured` and `/items/{id}` keep the loop free while Supabase is slow, and return unchanged payloads.
- [x] **Scenario 4:** `POST /payment/webhook` keeps the loop free while fulfilment is slow, and still returns 200 / 503-on-retryable-error as before.

# Implementation Files
- `backend/auth_middleware.py` - off-loop token and ban lookups.
- `backend/routes/items.py` - off-loop storefront reads.
- `backend/routes/payment.py` - off-loop webhook verification and fulfilment.
- `backend/routes/user.py`, `backend/routes/admin.py` - off-loop avatar uploads, item updates and market valuation.
- `backend/notifications.py` - bounded Redis connect/close so the lifespan can never hang on it.
- `backend/tests/test_auth_middleware.py`, `backend/tests/test_routes_items.py`, `backend/tests/test_routes_payment.py` - coverage.
