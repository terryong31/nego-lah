# Monorepo Structure & Tooling Guide

This document explains the organization of the **Nego-Lah** monorepo, its workspace conventions, and its development toolchain.

---

## 1. Directory Layout

```text
nego-lah/
├── frontend/             # Nuxt 4 Single Page Application (Cloudflare Pages)
│   ├── app/              # Vue 3 components, pages, layouts, composables, stores
│   ├── i18n/             # Trilingual message catalogues (en, ms, zh)
│   ├── tests/            # Vitest unit & component test suites
│   ├── nuxt.config.ts    # SPA configuration, runtime configs, Nuxt UI & Tailwind v4
│   └── wrangler.toml     # Cloudflare Pages deployment configuration
│
├── backend/              # FastAPI Modular Monolith (AWS Lightsail)
│   ├── agent/            # LangGraph supervisor, sub-agents, tools, memory
│   ├── domains/          # Bounded business domains (catalog, negotiation, billing, identity, webhooks)
│   ├── routes/           # HTTP controllers, including admin console API
│   ├── core/             # Cross-cutting infrastructure (config, database pool, security, uploads)
│   ├── services/         # Transactional email & buffered notification digests
│   ├── payment/          # Stripe checkout, webhooks, fulfillment state machine
│   ├── templates/        # Jinja "Ledger" transactional email templates
│   ├── tests/            # Pytest test suites with async fixtures (88% coverage gate)
│   └── Dockerfile        # Production multi-stage container image
│
├── supabase/             # Database schemas, RLS policies, migrations, auth templates
│   ├── migrations/       # Sequential SQL migrations (baseline through current)
│   ├── templates/        # Supabase Auth email templates
│   └── config.toml       # Supabase CLI and local environment configuration
│
├── docs/                 # Engineering Documentation Hub (Diátaxis framework)
│   ├── adr/              # Architecture Decision Records (ADR-0001 … ADR-0024)
│   ├── api/              # OpenAPI 3.1 specification (openapi.json) and API guide
│   ├── architecture/     # LeanSpec system architecture & agent graphs
│   ├── ci-cd/            # CI/CD deployment pipelines & GitHub Actions
│   ├── data/             # Database models, schema diagrams, RLS & storage docs
│   ├── repo/             # Monorepo structure and conventions (this document)
│   ├── security/         # Security anti-patterns & penetration testing standards
│   ├── specs/            # LeanSpec specifications (SPEC-001 … SPEC-071)
│   └── workers/          # Lifespan background worker loops
│
├── api/                  # Root mirror for OpenAPI specification
│   └── openapi.json      # OpenAPI 3.1 schema
│
├── .github/              # Automation & GitHub Actions workflows
│   └── workflows/        # Path-filtered CI/CD pipeline (deploy.yml)
│
├── docker-compose.yml    # Production container orchestration (FastAPI + Caddy + Redis)
├── Caddyfile             # TLS termination, reverse proxy, and security headers
├── lefthook.yml          # Git pre-commit and pre-push hooks
├── mise.toml             # Universal environment and task orchestrator
└── AGENTS.md             # AI Agent rules of engagement (LeanSpec enforced)
```

---

## 2. Toolchain & Runtime Management

The repository uses [**mise**](https://mise.jdx.dev/) as the single source of truth for runtime versions and tasks:

| Tool | Managed By | Purpose |
| :--- | :--- | :--- |
| **`uv`** | mise | Ultra-fast Python package resolver and virtualenv manager (`backend/.venv`). |
| **`bun`** | mise | Fast JavaScript package manager and runtime for the frontend. |
| **`infisical`** | mise | Centralized secrets manager injecting credentials across `dev` and `prod`. |
| **`lefthook`** | mise | Fast Git pre-commit (lint) and pre-push (test) runner. |

---

## 3. Domain Isolation Discipline (Backend)

In `backend/domains/`, business logic is strictly partitioned into domain packages:
- **`catalog`**: Inventory listings, search, image normalization, categories.
- **`negotiation`**: Multi-turn bargaining, LangGraph supervisor, LLM factory, dynamic failover.
- **`billing`**: Stripe checkout session generation, optimistic inventory claim locks, refunds.
- **`identity`**: User profiles, custom avatars, admin 2FA OTP verification, CSRF tokens.
- **`webhooks`**: Ingesting Stripe and Resend external webhook events.

### Domain Rules:
1. **Never reach into another domain's database queries:** Domains must not import or query private tables of another domain. Cross-domain queries are conducted solely through exported Domain Services (`CatalogService`, `BillingService`).
2. **Encapsulated State:** All payment lock handling stays strictly within `billing`. All conversation state stays in `negotiation`.
3. **2 GB RAM Envelope:** No heavyweight background processes (Celery/RabbitMQ). Tasks run inside the FastAPI event loop lifespan.
