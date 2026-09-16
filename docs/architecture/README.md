# Architecture Overview

This directory provides the conceptual and structural architecture documentation for **Nego-Lah**, organized by architectural domain following the **Diátaxis Explanation** quadrant and **LeanSpec** design standards.

---

## Architectural Categories

Explore detailed design specifications across core domains:

- **[Agent Architecture](agent/README.md):** Unified ReAct negotiation engine, direct tool bindings, request-scoped context, and prompt caching.
- **[System Architecture](system/README.md):** End-to-end topology, Cloudflare edge routing, AWS Lightsail VPS, Redis lease concurrency, and lifespan background workers.
- **[Database & Storage Architecture](db/README.md):** PostgreSQL schema design, confidential floor price column security, optimistic checkout claims, and media CDN.

---

## Primary Specifications & Master Blueprint

For the original end-to-end specification and system blueprints:
- **[SPEC-000: System Architecture & AI Negotiation Engine](./SPEC-000-system-architecture.md)**
- **[SPEC-079: Unified Single-Agent Architecture](../specs/SPEC-079-unified-single-agent-architecture.md)**

---

## Architectural Decision Records (ADRs)

All architectural pivot points and design patterns are documented in [`docs/adr/`](../adr/README.md):
- [ADR 0001: Payment Concurrency Optimistic Claim](../adr/0001-payment-concurrency-optimistic-claim.md)
- [ADR 0002: Modular Monolith Architecture](../adr/0002-modular-monolith-over-grpc-microservices.md)
- [ADR 0004: Nuxt SPA on Cloudflare Pages](../adr/0004-nuxt-spa-cloudflare-pages-and-turnstile.md)
- [ADR 0007: Hybrid Edge-Cloud LLM Load Balancer](../adr/0007-hybrid-edge-cloud-llm-load-balancer.md)
- [ADR 0009: Confidential Columns Enforced in Postgres](../adr/0009-confidential-columns-enforced-in-postgres.md)
- [ADR 0026: Unified Single-Agent Architecture with Direct Tool Calling](../adr/0026-unified-single-agent-architecture.md)
