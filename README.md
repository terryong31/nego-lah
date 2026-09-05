# Nego-lah

A second-hand marketplace where prices aren't fixed — buyers negotiate with an AI agent, or a human admin who can step into the chat, before checking out.

## Features

- Browse and search listings
- Real-time negotiation chat, streamed token-by-token
- LangGraph agent that looks up items, checks market prices, applies discount logic, and can generate a Stripe checkout link without leaving the conversation
- Stripe checkout with idempotent, race-safe order fulfillment (see [docs/adr/0001](docs/adr/0001-payment-concurrency-optimistic-claim.md))
- Admin console — items, orders, users, live chat takeover, audit log, 2FA login
- Dark/light theme

## Tech Stack

**Frontend** — Nuxt 4 (Vue 3), TypeScript, Tailwind CSS 4 + Nuxt UI 4, Bun, Supabase client

**Backend** — FastAPI, LangGraph + Gemini, Stripe, Redis, Supabase (Postgres, Auth, Storage)

## Architecture

### System Overview

```mermaid
graph TD
    Client([Browser Client])

    subgraph CICD["CI/CD"]
        GHA["GitHub Actions\n(test, build, push)"]
        GHCR[("GHCR\nimage registry")]
        GHA -->|push image| GHCR
    end

    subgraph Lightsail["AWS Lightsail instance"]
        Caddy["Caddy\n(TLS termination + reverse proxy)"]
        Frontend["Frontend container\nNuxt 4 SSR (Nitro :3000)"]
        Backend["Backend container\nFastAPI (:8000)\nLangGraph agent + payment-cleanup loop"]
        Redis[("Redis\nsessions / rate-limit / cache")]

        Caddy -->|"/api/*"| Backend
        Caddy -->|"everything else"| Frontend
        Backend --> Redis
    end

    Supabase[("Supabase\nPostgres + Auth + Storage")]
    Gemini["Gemini API"]
    Stripe["Stripe"]
    Resend["Resend\n(inbound + outbound email)"]
    Sentry["Sentry\n(errors, logs, profiling)"]

    Client -->|HTTPS| Caddy
    Frontend -->|client SDK| Supabase
    Backend -->|Postgres/Auth/Storage| Supabase
    Backend --> Gemini
    Backend --> Stripe
    Backend <-->|webhook + forward| Resend
    Backend --> Sentry

    GHCR -.->|"docker compose pull"| Lightsail

    classDef infra fill:#d1e7dd,stroke:#0f5132,color:#000
    classDef store fill:#cfe2ff,stroke:#084298,color:#000
    classDef external fill:#fff3cd,stroke:#856404,color:#000

    class Caddy,Frontend,Backend infra
    class Redis,Supabase,GHCR store
    class Gemini,Stripe,Resend,Sentry,GHA external
```

### Agent Architecture

The agent side is a supervisor (Customer Agent) delegating to two specialized sub-agents:

```mermaid
graph TD
    User([User]) --> |chat| CustomerAgent["Customer Agent (Supervisor)"]
  
    subgraph Customer Agent Tools
        ItemAgent["Item Agent"]
        StripeAgent["Stripe Agent"]
        EvalOffer["evaluate_offer"]
        Discount["assess_discount_eligibility"]
        WebSearch["web_search"]
        Orders["check_user_orders"]
    end

    CustomerAgent -->|call_item_agent| ItemAgent
    CustomerAgent -->|call_stripe_agent| StripeAgent
    CustomerAgent -->|evaluate_offer| EvalOffer
    CustomerAgent -->|assess_discount_eligibility| Discount
    CustomerAgent -->|web_search| WebSearch
    CustomerAgent -->|check_user_orders| Orders

    subgraph Item Agent Tools
        GetItemInfo["get_item_info"]
        SearchItems["search_items"]
        ListItems["list_all_items"]
    end

    ItemAgent -->|get_item_info| GetItemInfo
    ItemAgent -->|search_items| SearchItems
    ItemAgent -->|list_all_items| ListItems
  
    subgraph Stripe Agent Tools
        CreateLink["create_checkout_link"]
        CancelPayment["cancel_payment"]
        ShippingInfo["save_shipping_info"]
    end

    StripeAgent -->|create_checkout_link| CreateLink
    StripeAgent -->|cancel_payment| CancelPayment
    StripeAgent -->|save_shipping_info| ShippingInfo

    classDef agent fill:#d1e7dd,stroke:#0f5132,color:#000
    classDef tool fill:#fff3cd,stroke:#856404,color:#000
  
    class CustomerAgent,ItemAgent,StripeAgent agent
    class EvalOffer,Discount,WebSearch,Orders,GetItemInfo,SearchItems,ListItems,CreateLink,CancelPayment,ShippingInfo tool
```

## Getting Started

### Prerequisites

- [Bun](https://bun.sh)
- Python 3.12
- Redis — the backend depends on it directly (admin sessions, rate limiting, caching) and won't start without it
- A Supabase project and the [Supabase CLI](https://supabase.com/docs/guides/cli)

### 1. Clone and set up the database

```bash
git clone https://github.com/terryong31/nego-lah.git
cd nego-lah

supabase login
supabase link --project-ref <your-project-ref>
supabase db push
```

See [supabase/README.md](supabase/README.md) for the RLS model and the admin-auth design.

### 2. Backend

```bash
cd backend
uv sync
cp .env.example .env   # fill in Supabase, Gemini, Stripe, Redis values
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend

```bash
cd frontend
bun install
```

Create `frontend/.env`:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
```

```bash
bun run dev
```

Frontend: `http://localhost:3000` · Backend: `http://localhost:8000`

### 4. Create an admin

```bash
# from backend/, with the venv active
python -m scripts.create_admin you@example.com 'your-password'
```

Log in at `/_console/login` — password, then a 6-digit code emailed to you.

---

Alternatively, `docker compose up --build` runs all four services (Caddy, frontend, backend, Redis) together — still needs `backend/.env` and `frontend/.env` populated first.

## License

All rights reserved — see [LICENSE](LICENSE). The source is here to read, not to reuse, modify, or redistribute.

---

[Terry Ong](https://github.com/terryong31) © 2026
