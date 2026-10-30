# Nego-Lah

> **A single-seller second-hand store where an AI agent haggles with buyers in real time. Can nego until happy, settle the deal on the spot!**

[![Frontend CI](https://img.shields.io/badge/Frontend-Nuxt%204%20SPA%20%7C%20Cloudflare%20Pages-F38020?logo=cloudflare)](https://negolah.my)
[![Backend API](https://img.shields.io/badge/Backend-FastAPI%20%7C%20AWS%20Lightsail-FF9900?logo=amazon-aws)](https://api.negolah.my)
[![Database](https://img.shields.io/badge/Database-Supabase%20Postgres-3ECF8E?logo=supabase)](https://supabase.com)
[![Secrets](https://img.shields.io/badge/Secrets-Infisical%20Cloud-000000?logo=infisical)](https://infisical.com)
[![Documentation](https://img.shields.io/badge/Docs-Diátaxis%20Hub-blueviolet)](docs/)

---

## Objective of This Project

*"Is this item still available?"* This phrase sounds familiar, right? Especially if you sell second-hand items online. You reply *"Yes, still available!"*, and then boom: ghosted immediately. Or worse, you get hit with *"best price bro"*, *"RM50 can bro?"* for an RM300 item, or endless questions before disappearing into thin air. Selling preloved stuff shouldn't feel like a full-time unpaid customer service job!

**Nego-Lah** is my answer: my own preloved store, live at [negolah.my](https://negolah.my), where an AI agent answers buyers and negotiates on my behalf 24/7. It is not a toy demo. Real buyers have paid real money through it for 4 of my personal items. It is also small: one seller (me), a handful of sales, and a single 2 GB server.

Here is how Nego-Lah settles the deal:

1. **Auto-Nego with Floor Price Protection:** Buyers can bargain token-by-token in real-time. The AI agent speaks fluent English, Malay, and Mandarin. It makes small, whole-number concessions. The floor price never reaches the model at all: Postgres column privileges hide it from the public API, pricing is computed in Python rather than by the LLM, and checkout refuses any price the server did not actually quote.
2. **Instant Checkout Inside Chat:** Once a price is agreed upon, the AI generates a Stripe payment link directly in the chat bubble. The item is claimed atomically when payment lands, and a buyer who loses a race is refunded automatically, so an item can't be sold twice and nobody can reserve one without paying.
3. **Human Takeover (HITL) Anytime:** If a buyer wants Cash on Delivery (COD) or has special requests, the agent hands the chat to the seller, who replies from the admin console while the AI stays switched off.

No drama, no lowballer fatigue, everything settles automatically!

---

## Engineering Highlights

The interesting problems were not "call an LLM". Each of these came from something that broke or was measured:

- **Decide, then speak.** On the self-hosted Qwen (about 3B active parameters), a normal ReAct agent stopped calling tools once the context held any chat history: 3/3 tool calls with no history, 0/3 after one prose reply. Splitting each turn into a routing call with no transcript and a speaking call with no tools took routing from 3/7 to 7/8 and cut turn latency from 6.5 s to 3.0 s. See [SPEC-091](docs/specs/SPEC-091-local-decide-then-speak-agent.md) and [`decide.py`](backend/domains/negotiation/decide.py).
- **The server owns the price, not the model.** In one eval run the model passed its own last quote as 0 on 13 of 13 calls, so it kept re-quoting the listed price after conceding. The standing price now lives server-side, and checkout refuses any price the server didn't quote (SPEC-084, SPEC-089).
- **A laptop as an LLM server.** Apple Silicon serves one stream well, so the laptop is a pool of one, guarded by an atomic Redis lease with an owner token. Every other turn overflows to Gemini with no wait ([`llm_factory.py`](backend/domains/negotiation/llm_factory.py)).
- **An enforced modular monolith.** Four layered domains; a test parses every import and table access and fails the build on a back-edge or a cycle ([ADR-0030](docs/adr/0030-the-domain-graph-is-acyclic.md)).

**Agent evals.** `mise run eval:agent` replays 14 scripted buyer conversations against a real model and scores them on hard rules: no floor claims, no price the tools didn't authorise, a tool call on every price turn, a checkout link only after explicit agreement. Results on `gemini-3.8-flash` (the cloud path), 2026-10-11:

| Run | Passed | Cost per scenario |
| --- | --- | --- |
| Before [SPEC-106](docs/specs/SPEC-106-cloud-prompt-bans-false-floor-claims.md) | 12 / 14 | RM0.033 |
| After SPEC-106, 3 repeats | 42 / 42 | RM0.033 |

Both failures were the agent calling a price above the floor "the best I can do", which ends a haggle early at a false limit. The real floor never appeared in any reply. The set is small and hand-written, so read this as a regression gate, not a benchmark. The self-hosted model has not been re-scored on this suite.

**How it was built.** I wrote this with heavy use of AI coding tools (Claude Code). The decisions, the measurements and the debugging above are mine, and the process is visible in the repo: a short spec before each change ([`docs/specs/`](docs/specs/)), tests written first, and architectural decisions recorded as ADRs.

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

MIT License. See [LICENSE](LICENSE).

[Terry Ong](https://github.com/terryong31) © 2026
