---
id: SPEC-092
title: Backend Modular Monolith Realization — Code Relocation & Domain Boundaries
status: complete
priority: high
created: 2026-09-17
tags: [backend, architecture, modular-monolith, domain-services, boundaries]
assigned: agent
---

# Context & Objectives
ADR-0002 and SPEC-002 declared a Modular Monolith of 5 bounded domains, but `domains/` held only re-export stubs: all business logic lived in `agent/`, `payment/`, `routes/` and `items.py`, and the boundary test walked only `domains/`, where nothing could violate it.

This spec covers the actual migration: **the code moved**. Every module now lives in the domain that owns it, shared infrastructure lives in `core/`, and the boundary is a directory rather than a convention.

# Acceptance Criteria
- [x] All business logic lives under `backend/domains/<name>/`. `agent/`, `payment/` and `routes/` are gone, not shimmed.
- [x] Shared infrastructure consolidated in `core/` (config, cache, connectors, logging, limiter, CSRF, schemas, notifications, broadcast).
- [x] **Zero** cross-domain table access. Was 29 sites; now 0, with an empty `KNOWN_VIOLATIONS` ratchet.
- [x] **Zero** cross-domain private-module imports. A domain may only import another domain's *package* (its exported service/contract).
- [x] Four domain services exist and every one has production callers: `CatalogService`, `BillingService`, `IdentityService`, `NegotiationService`.
- [x] `main.py` mounts each domain's own router; the cross-domain admin console is composed in `admin_api.py`.
- [x] Route table byte-identical to pre-migration: **59 operations across 53 paths**, verified by diffing the OpenAPI schema against a clean `HEAD` worktree.
- [x] `mise run test:backend` passes (1,765 tests) with coverage ≥88% (90.10%). `ruff check` and `typecheck` clean.
- [x] Boot cost unchanged (~340 ms, ~95 MB RSS): domain packages resolve routers and the agent lazily via `__getattr__`.

# Technical Design & Contracts
```
backend/
├── main.py              app factory
├── admin_api.py         composes the admin console across domains (gating lives here)
├── admin_dashboard.py   cross-domain summary; asks each domain for its own numbers
├── core/                config, env, cache, connector, logger, limiter, csrf,
│                        schemas, notifications, broadcast, database, security,
│                        telemetry, images, uploads, jwt_auth, middleware
└── domains/
    ├── catalog/      items, routes, admin_routes, admin_listings, shipping, services
    ├── negotiation/  bot, tools/, sub_agents/, memory, decide, llm_factory, routes, services
    ├── billing/      fulfillment, pay, payment_state, pricing, refunds, webhooks, routes, services
    ├── identity/     auth_middleware, admin_session, profiles, routes, admin_*, services
    └── webhooks/     routes
```

**Table ownership** — `items`→catalog, `orders`/`transactions`→billing, `messages`/`chat_settings`→negotiation, `user_profiles`/`admin_audit_log`→identity.

**Package `__init__` is the contract.** Logic lives inside each package, so an eager import in `__init__` would re-enter the package mid-import. Every domain exports through `domains/_lazy.py`'s `lazy_getattr`, which also keeps `agent.bot` (LangChain, +430 ms / +70 MB RSS per worker) out of boot.

**`claim_item_as_sold` must not swallow database errors.** `False` means *another buyer holds this item*, and billing answers a lost claim by **refunding**. A swallowed transient failure would auto-refund a good payment; propagating makes the Stripe webhook return 5xx so the payment is redelivered. Cache invalidation stays in `_finalize_won_sale` for the same reason — a Redis blip must not veto a committed sale.

# TDD Scenarios
- [x] `test_domain_boundaries.py` derives a file's domain **from its path**, then fails on (a) any cross-domain `.table("…")`, (b) any cross-domain private-module import, (c) any file querying a table from outside a domain, (d) a stale `KNOWN_VIOLATIONS` entry. Both failure directions verified by injection.
- [x] `CatalogService` tests assert the columns and filters sent to PostgREST (`PUBLIC_ITEM_SELECT`, `deleted_at is null`, `status = available`), not that a MagicMock echoes its fixture.
- [x] `claim_item_as_sold` raises rather than reporting a lost claim when the UPDATE errors.
- [x] `test_payment_fulfillment.py`: a transient DB error during the claim issues **no refund**; a Redis failure after a won claim still returns `fulfilled`.

# Follow-ups (not in scope here)
- `core/config.py` and `core/env.py` still duplicate 27 keys; one should go.
- `services/` (email, digests) is shared across domains and has not been re-homed.
