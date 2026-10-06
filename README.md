# Nego-Lah

> **Autonomous second-hand marketplace with real-time AI price negotiations. Can nego until happy, settle the deal on the spot!**

[![Frontend CI](https://img.shields.io/badge/Frontend-Nuxt%204%20SPA%20%7C%20Cloudflare%20Pages-F38020?logo=cloudflare)](https://negolah.my)
[![Backend API](https://img.shields.io/badge/Backend-FastAPI%20%7C%20AWS%20Lightsail-FF9900?logo=amazon-aws)](https://api.negolah.my)
[![Database](https://img.shields.io/badge/Database-Supabase%20Postgres-3ECF8E?logo=supabase)](https://supabase.com)
[![Secrets](https://img.shields.io/badge/Secrets-Infisical%20Cloud-000000?logo=infisical)](https://infisical.com)
[![Documentation](https://img.shields.io/badge/Docs-Diátaxis%20Hub-blueviolet)](docs/)

---

## Objective of This Project

*"Is this item still available?"* This phrase sounds familiar, right? Especially if you sell second-hand items online. You reply *"Yes, still available!"*, and then boom: ghosted immediately. Or worse, you get hit with *"best price bro"*, *"RM50 can bro?"* for an RM300 item, or endless questions before disappearing into thin air. Selling preloved stuff shouldn't feel like a full-time unpaid customer service job!

**Nego-Lah** was built to solve this once and for all by letting an autonomous AI agent run the entire storefront and handle negotiations 24/7. And this isn't just a toy demo: this platform is **battle-tested in production**, having successfully sold a total of 4 personal items while serving more than 20 users concurrently without a single second of downtime.

Here is how Nego-Lah settles the deal:

1. **Auto-Nego with Floor Price Protection:** Buyers can bargain token-by-token in real-time. The AI agent speaks fluent English, Malay, and Mandarin. It knows how to make reasonable concessions, but will *never* leak or breach your secret floor price.
2. **Instant Checkout Inside Chat:** Once a price is agreed upon, the AI generates a Stripe payment link directly in the chat bubble. Atomic claim-at-payment with auto-refund protection: zero double-selling, zero joybidders!
3. **Human Takeover (HITL) Anytime:** If a buyer wants Cash on Delivery (COD) or has special requests, the agent hands the chat to the seller, who replies from the admin console while the AI stays switched off.

No drama, no lowballer fatigue, everything settles automatically!

---

## Tech Stack Overview

- **Frontend:** Nuxt 4 Single Page Application (`ssr: false`), Nuxt UI, TailwindCSS v4, deployed to Cloudflare Pages edge.
- **Backend:** FastAPI modular monolith on an AWS Lightsail instance (2 GB RAM), with managed Redis (Upstash).
- **AI Brain:** Hybrid Edge/Cloud LLM: self-hosted `Qwen3.6-35B-A3B` on local Apple Silicon M5 hardware via Cloudflare Tunnel, with automatic overflow to Google Gemini (`gemini-3.8-flash`).
- **Database & Storage:** Supabase PostgreSQL with column-level security, Supabase Storage for images, Cloudflare R2 for video.

---

## Quickstart Guide

Everything runs through [**mise**](https://mise.jdx.dev/). It manages `uv`, `bun`, `infisical`, and `lefthook` for you.

```bash
# 1. Install pinned tools & dependencies
mise install
(cd frontend && bun install)
mise run hooks:install

# 2. Run full local stack (Redis + FastAPI :8000 + Nuxt :3000)
mise run dev

# 3. Run all tests (Backend pytest + Frontend vitest)
mise run test
```

Need to run services one by one? Easy:

- `mise run dev:backend`: Backend only
- `mise run dev:frontend`: Frontend only
- `mise run lint`: Ruff + ESLint checks

---

## Documentation

Engineering docs live in [`docs/`](docs/README.md), which starts with a "which page do I need" table.

- **[Architecture](docs/architecture/README.md)** and **[Agent architecture](docs/architecture/agent.md)**: components, domain layering, model routing, and the pricing rules the server enforces.
- **[Data model](docs/data/README.md)**: tables, ownership, confidential columns.
- **[API reference](docs/api/README.md)**: cookie auth, route groups, and the generated [OpenAPI 3.1 spec](docs/api/openapi.json).
- **[Getting started](docs/tutorials/getting-started.md)** and **[how-to guides](docs/how-to/README.md)**: run it and haggle once; then migrations, deploys and roll back.
- **[ADRs](docs/adr/README.md)** and **[specs](docs/specs/README.md)**: why each decision was made, and the contract for each change.

---

## License

All rights reserved. See [LICENSE](LICENSE).

[Terry Ong](https://github.com/terryong31) © 2026
