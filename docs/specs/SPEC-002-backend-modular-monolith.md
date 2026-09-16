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
- [x] Backend is organized into `core/` and bounded `domains/` (`catalog`, `negotiation`, `billing`, `identity`, `webhooks`).
- [x] No domain directly queries or accesses another domain's private schemas or state. Cross-domain interactions pass through exported Domain Services (`CatalogService`, `BillingService`).
- [x] Configuration is strongly typed via Pydantic Settings in `core/config.py`.
- [x] All existing test suites pass without regression after refactoring (876 tests green).
- [x] Single FastAPI application mounts domain routers cleanly in `main.py`.

# Technical Design & Contracts
```
backend/
├── core/
│   ├── config.py
│   ├── database.py
│   ├── cache.py
│   ├── security.py
│   └── telemetry.py
└── domains/
    ├── catalog/
    ├── negotiation/
    ├── billing/
    ├── identity/
    └── webhooks/
```

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1:** Domain service functions execute and return typed schemas without circular imports.
- [ ] **Scenario 2:** Rate limiting and session validation in `core/security.py` properly protect domain endpoints.
- [ ] **Scenario 3:** Complete regression test suite passes with `uv run pytest`.

# Implementation Files
- `backend/core/*` - Shared infrastructure
- `backend/domains/*` - Domain services and routers
- `backend/main.py` - Application factory
