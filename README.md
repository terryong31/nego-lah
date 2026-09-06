# Nego-Lah!

> **An autonomous second-hand marketplace with real-time AI price negotiations powered by a hybrid edge/cloud dual-LLM architecture.**

[![Frontend CI](https://img.shields.io/badge/Frontend-Nuxt%204%20SPA%20%7C%20Cloudflare%20Pages-F38020?logo=cloudflare)](https://negolah.my)
[![Backend API](https://img.shields.io/badge/Backend-FastAPI%20%7C%20AWS%20Lightsail-FF9900?logo=amazon-aws)](https://api.negolah.my)
[![Database](https://img.shields.io/badge/Database-Supabase%20Postgres-3ECF8E?logo=supabase)](https://supabase.com)
[![Secrets](https://img.shields.io/badge/Secrets-Infisical%20Cloud-000000?logo=infisical)](https://infisical.com)
[![Architecture](https://img.shields.io/badge/Architecture-LeanSpec%20%7C%20Modular%20Monolith-blueviolet)](specs/)

---

## Features & Highlights

- **Real-Time Streaming Negotiation:** Token-by-token Server-Sent Events (SSE) chat with natural conversational pacing, typing indicators, and trilingual mastery (English, Manglish/Malay, Chinese).
- **Hybrid Dual-LLM Architecture:** Self-hosted `Qwen3.6-35B-A3B-4bit` running locally on Apple Silicon M5 hardware via Cloudflare Tunnel (`https://llm.negolah.my`), backed by sub-second automatic fallback to Google Gemini (`gemini-2.5-flash`).
- **Private Floor Price Guardrails:** Sellers define hidden minimum floor prices and target margins. The agent defends margins, evaluates offers dynamically, and never leaks seller limits — the floor is withheld at both layers: it is absent from every public API response, and `anon`/`authenticated` hold only column-scoped `SELECT` on `items`, so the browser's Supabase key cannot read it either ([ADR-0009](docs/adr/0009-confidential-columns-enforced-in-postgres.md)).
- **Race-Safe Stripe Checkout:** Direct checkout link generation inside chat bubbles with optimistic inventory reservation, Redis atomic lock acquisition, and idempotent webhook reconciliation ([ADR-0001](docs/adr/0001-payment-concurrency-optimistic-claim.md)).
- **Human-in-the-Loop (HITL) Takeover:** Sellers and administrators can monitor live negotiations and seamlessly take over chats with visual handover indicators and real-time SSE updates ([SPEC-019](specs/SPEC-019-realtime-chat-hitl-mobile-console-notifications.md)).
- **High-Performance Edge SPA:** Client-side Nuxt 4 Single Page Application (`ssr: false`) deployed to Cloudflare Pages edge network with Cloudflare Turnstile bot verification and PWA service worker caching ([ADR-0004](docs/adr/0004-nuxt-spa-cloudflare-pages-and-turnstile.md)).
- **Media & Asset CDN:** FastStart progressive HTTP 206 streaming for product showcase video demo and high-DPI assets hosted on Supabase Storage CDN ([SPEC-028](specs/SPEC-028-storage-cdn-assets.md)).
- **Zero-Trust Secrets Management:** Environment-segregated configurations (`dev`, `prod`) injected dynamically via Infisical Cloud ([ADR-0005](docs/adr/0005-infisical-secrets-management-and-api-domain.md)).

---

## System Architecture

```mermaid
graph TB
    subgraph Clients["Clients & Edge"]
        Browser(["Browser Client (negolah.my)"])
        CFPages["Cloudflare Pages (Nuxt 4 SPA)"]
        CFTunnel["Cloudflare Tunnel (llm.negolah.my)"]
    end

    subgraph AWS["AWS Lightsail (api.negolah.my)"]
        Caddy["Caddy (TLS Termination & Reverse Proxy)"]
        FastAPI["FastAPI Modular Monolith (:8000)"]
        Redis[("Redis 7\n(Sessions / Locks / Rate Limits)")]

        Caddy -->|Reverse Proxy| FastAPI
        FastAPI <--> Redis
    end

    subgraph LocalAI["Edge Local AI Node"]
        M5Mac["Apple Silicon M5 Hardware"]
        LocalLLM["Qwen3.6-35B-A3B (vLLM / llama.cpp)"]
        M5Mac --- LocalLLM
    end

    subgraph CloudServices["Managed Cloud Services"]
        Supabase[("Supabase\nPostgreSQL + Auth + Storage CDN")]
        Gemini["Google Gemini API\n(Automatic Cloud Failover)"]
        Stripe["Stripe API & Webhooks"]
        Resend["Resend (Transactional Email)"]
        Infisical["Infisical Cloud (Secrets)"]
    end

    Browser -->|HTTPS / Assets| CFPages
    Browser -->|REST & SSE Events| Caddy
    Browser -->|Auth & CDN Assets| Supabase

    FastAPI -->|Primary LLM Stream| CFTunnel
    CFTunnel --> LocalLLM
    FastAPI -.->|Failover on Error/Timeout| Gemini

    FastAPI <-->|asyncpg Pool / RLS| Supabase
    FastAPI <-->|Checkout / Events| Stripe
    FastAPI -->|Notifications| Resend
    Infisical -.->|Inject Env Secrets| FastAPI
    Infisical -.->|Inject Build Secrets| CFPages
```

---

## Negotiation Agent Graph (LangGraph)

The negotiation engine uses a state-machine supervisor architecture coordinating specialized tools:

```mermaid
graph TD
    User([Buyer Chat Message]) --> Supervisor["Customer Agent (Supervisor)"]

    subgraph Agents["Specialized Sub-Agents"]
        ItemAgent["Item Agent"]
        StripeAgent["Stripe Agent"]
    end

    subgraph Tools["Domain & Guardrail Tools"]
        EvalOffer["evaluate_offer\n(Floor Price & Margin Guardrails)"]
        Discount["assess_discount_eligibility"]
        WebSearch["web_search\n(Market Benchmarking)"]
        Orders["check_user_orders"]
    end

    Supervisor -->|delegates listing queries| ItemAgent
    Supervisor -->|delegates payment creation| StripeAgent
    Supervisor -->|evaluates bid| EvalOffer
    Supervisor -->|checks discounts| Discount
    Supervisor -->|checks comp prices| WebSearch
    Supervisor -->|verifies customer| Orders

    subgraph ItemTools["Catalog Inspection"]
        ItemAgent --> GetItem["get_item_info"]
        ItemAgent --> SearchItems["search_items"]
        ItemAgent --> ListItems["list_all_items"]
    end

    subgraph StripeTools["Order & Payment Pipeline"]
        StripeAgent --> CreateLink["create_checkout_link"]
        StripeAgent --> CancelPayment["cancel_payment"]
        StripeAgent --> Shipping["save_shipping_info"]
    end

    classDef supervisor fill:#3b82f6,stroke:#1d4ed8,color:#fff
    classDef agent fill:#10b981,stroke:#047857,color:#fff
    classDef tool fill:#f59e0b,stroke:#b45309,color:#fff

    class Supervisor supervisor
    class ItemAgent,StripeAgent agent
    class EvalOffer,Discount,WebSearch,Orders,GetItem,SearchItems,ListItems,CreateLink,CancelPayment,Shipping tool
```

---

## Monorepo Structure

```text
nego-lah/
├── frontend/             # Nuxt 4 SPA (Cloudflare Pages)
│   ├── app/              # Vue 3 components, pages, layouts, composables
│   ├── tests/            # Vitest unit & component test suites (760+ tests)
│   └── wrangler.toml     # Cloudflare Pages deployment configuration
├── backend/              # FastAPI Modular Monolith (AWS Lightsail)
│   ├── domains/          # Domain-driven architecture (catalog, negotiation, billing, etc.)
│   ├── tests/            # Pytest test suites with async fixtures
│   ├── Dockerfile        # Production container image
│   └── docker-compose.yml# Production stack orchestration
├── specs/                # LeanSpec Spec-Driven Development documents (SPEC-001 to SPEC-028)
├── docs/adr/             # Architectural Decision Records (ADR-0001 to ADR-0007)
├── supabase/             # Postgres schemas, RLS policies, migrations, and seeds
├── .github/workflows/    # Optimized parallel GitHub Actions CI/CD pipelines
├── mise.toml             # Universal environment and task orchestrator
└── README.md
```

---

## Developer Quickstart

The project uses [**mise**](https://mise.jdx.dev/) for deterministic toolchain management (`python 3.12`, `bun`, `uv`, `infisical`).

### 1. Prerequisites

Ensure `mise` is installed:
```bash
# macOS / Linux
curl https://mise.run | sh
```

Install repository dependencies and runtimes:
```bash
git clone https://github.com/terryong31/nego-lah.git
cd nego-lah
mise install
```

### 2. Environment Configuration (via Infisical)

All secrets are managed centrally through Infisical:
```bash
# Login to Infisical Cloud
infisical login

# Pull development secrets directly or run transparently
infisical run --env=dev -- mise run dev
```

*(Alternatively, copy `.env.example` to `.env` in `frontend/` and `backend/` for offline local development).*

### 3. Running Locally

Start the full stack with a single command (Redis + FastAPI backend on `:8000` + Nuxt frontend on `:3000`):

```bash
# Start all services concurrently
mise run dev

# Or start services individually
mise run dev:backend
mise run dev:frontend
```

### 4. Running Tests & Quality Checks

```bash
# Run all test suites (Pytest + Vitest)
mise run test

# Run frontend tests & linting
mise run test:frontend
mise run lint
mise run typecheck

# Run backend tests
mise run test:backend
```

---

## CI/CD & Deployment

Deployments are fully automated via GitHub Actions on push to `main`, featuring path-filtered change detection to build, test, and deploy only the services modified:

```mermaid
graph TD
    Push([git push origin main]) --> Detect[Detect Changed Files]

    Detect -->|frontend modified| FLint["Frontend Lint & Typecheck"]
    Detect -->|frontend modified| FTest["Frontend Unit Tests (Vitest)"]
    Detect -->|backend modified| BTest["Backend CI (ruff, pytest)"]

    FLint & FTest --> DeployFront["Deploy Frontend\n(Wrangler -> Cloudflare Pages)"]
    BTest --> BuildBack["Build Docker Image\n(Push to GHCR)"]
    BuildBack --> DeployBack["Deploy Backend\n(SSH -> AWS Lightsail Compose Pull)"]
```

- **Path-Filtered Execution:** Non-code changes (documentation, specs, database schemas) bypass unnecessary compute. Modifications to frontend or backend run independently in parallel pipelines.
- **Frontend:** Built as a static SPA with environment secrets injected from Infisical and deployed to **Cloudflare Pages** at [`negolah.my`](https://negolah.my).
- **Backend:** Packaged into a multi-stage Docker image, pushed to GitHub Container Registry (`ghcr.io`), and deployed via zero-downtime SSH orchestration to **AWS Lightsail** at [`api.negolah.my`](https://api.negolah.my).

---

## Architectural Decisions & Specifications

For deep dives into design rationale and protocol contracts, refer to:

- [ADR-0001: Payment Concurrency & Optimistic Claim](docs/adr/0001-payment-concurrency-optimistic-claim.md)
- [ADR-0002: Modular Monolith Domain Boundaries](docs/adr/0002-modular-monolith-over-grpc-microservices.md)
- [ADR-0003: Dual-Provider Multimodal LLM Failover](docs/adr/0003-dual-provider-multimodal-llm-failover.md)
- [ADR-0004: Nuxt SPA on Cloudflare Pages & Turnstile](docs/adr/0004-nuxt-spa-cloudflare-pages-and-turnstile.md)
- [ADR-0005: Infisical Secrets Management & API Routing](docs/adr/0005-infisical-secrets-management-and-api-domain.md)
- [ADR-0007: Hybrid Edge/Cloud LLM Load Balancer](docs/adr/0007-hybrid-edge-cloud-llm-load-balancer.md)
- [LeanSpec Specifications Index](specs/)

---

## License

All rights reserved — see [LICENSE](LICENSE).

---

[Terry Ong](https://github.com/terryong31) © 2026
