---
id: SPEC-002
title: Backend Modular Monolith Architecture & Domain Isolation
status: complete
priority: high
created: 2026-09-04
tags: [backend, architecture, modular-monolith, lightsail]
assigned: agent
---

# Context & Objectives
To keep the backend manageable and clean without incurring the heavy memory footprint and operational complexity of distributed gRPC microservices on our 2 GB AWS Lightsail instance, we organize the FastAPI backend into an explicit **Modular Monolith**. Bounded contexts are separated into `domains/` with strict domain interfaces and shared infrastructure encapsulated in `core/`.

# Acceptance Criteria
- [x] Backend is organized into `core/` and bounded `domains/` (`catalog`, `negotiation`, `billing`, `identity`, `webhooks`). *Realized by SPEC-092 — the code actually moved; before that, `domains/` held only re-export stubs.*
- [x] No domain directly queries or accesses another domain's private schemas or state. Cross-domain interactions pass through exported Domain Services (`CatalogService`, `BillingService`, `IdentityService`, `NegotiationService`). *Enforced by `tests/test_domain_boundaries.py`, which AST-scans every table access and cross-domain import.*
- [ ] Configuration is strongly typed via Pydantic Settings in `core/config.py`. **Not done** — `core/config.py` and `core/env.py` are both plain `os.getenv` modules that duplicate 27 keys between them.
- [x] All existing test suites pass without regression after refactoring (1,765 tests green, 90.10% coverage).
- [x] Single FastAPI application mounts domain routers cleanly in `main.py`; the cross-domain admin console is composed in `admin_api.py`.

# Technical Design & Contracts
```
backend/
├── core/
│   ├── config.py
│   ├── database.py
│   ├── cache.py
│   ├── security.py
│   └── telemetry.py
└── domains/          # see SPEC-092 for the realized layout
    ├── catalog/       # items, routes, shipping, CatalogService
    ├── negotiation/   # bot, tools, sub_agents, memory, NegotiationService
    ├── billing/       # fulfillment, payment state, refunds, BillingService
    ├── identity/      # auth middleware, admin sessions, IdentityService
    └── webhooks/
```

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** Domain service functions execute and return typed schemas without circular imports. *Each domain package resolves its exports lazily (`domains/_lazy.py`) precisely because the logic now lives inside the package.*
- [x] **Scenario 2:** Rate limiting and session validation properly protect domain endpoints.
- [x] **Scenario 3:** Complete regression test suite passes with `uv run pytest`.

# Implementation Files
- `backend/core/*` - Shared infrastructure
- `backend/domains/*` - Domain services and routers
- `backend/main.py` - Application factory
