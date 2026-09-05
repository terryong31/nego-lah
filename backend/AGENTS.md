# Backend Agent Guide - Nego-Lah Modular Monolith

This directory contains the core API backend for **Nego-Lah**, built with **FastAPI**, **Redis**, and **LangGraph**, deployed to an **AWS Lightsail** instance (2 GB RAM).

---

## Architectural Principles: Modular Monolith

The backend is organized into explicit bounded domains to preserve clean separation without the operational overhead of microservices:

```
backend/
├── core/                                # Shared infrastructure & cross-cutting utilities
│   ├── config.py                        # Pydantic Settings (Infisical / env loaded)
│   ├── database.py                      # Supabase client singletons (user & admin)
│   ├── cache.py                         # Redis connection, token tracking, sliding rate limiter
│   ├── security.py                      # JWT verification, CSRF, Turnstile token validation
│   └── telemetry.py                     # Sentry initialization & structured logger
│
├── domains/                             # Bounded Business Domains
│   ├── catalog/                         # Product inventory, search, and items
│   ├── negotiation/                     # AI negotiation agent, chat history, multimodal LLM
│   ├── billing/                         # Stripe payments, checkout sessions, state machine
│   ├── identity/                        # User profiles, admin 2FA sessions, CSRF
│   └── webhooks/                        # Stripe webhook & Resend email webhook handlers
│
└── tests/                               # Comprehensive Pytest test suites
```

### Domain Boundary Rules:
1. **No Direct Inter-Domain DB Leaks:** A domain must not reach into another domain's private schemas or tables. Use the exported `Service` class (e.g. `CatalogService`, `BillingService`).
2. **Encapsulated State:** All payment lock handling stays strictly within `domains/billing`. All conversation state stays in `domains/negotiation`.
3. **Keep It Lightweight (2 GB VPS envelope):** Do not spawn multiple background sub-processes or large in-memory caches. Background tasks run on the event loop (e.g. expired payment link cleanup).

---

## AI & LLM Engine Rules

1. **Dynamic Availability & Failover (`domains/negotiation/llm_factory.py`):**
   - The factory checks if the self-hosted local model (`Qwen3.6-35B-A3B`) is accessible via local IP or a Cloudflare Tunnel.
   - The health status is probed asynchronously with a 1.5s timeout and cached in Redis for 30s to prevent per-request latency.
   - If reachable: Return `ChatOpenAI` targeting `LOCAL_LLM_BASE_URL`.
   - If unreachable or times out: Seamlessly fall back to `ChatGoogleGenerativeAI` (`gemini-3.8-flash`).
2. **Native Multimodal Support:**
   - Both `Qwen3.6-35B-A3B` and `Gemini` support native vision.
   - Format image payloads using the standard OpenAI schema: `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}`.
   - Listing analysis in `image_analyzer.py` uses this unified multimodal format.

---

## Test-Driven Development (TDD) Contract

1. Always write or update the specification in `/specs/SPEC-XXX-<name>.md` first.
2. Write tests in `backend/tests/` asserting the acceptance criteria.
3. Run `uv run pytest` to confirm tests fail (Red).
4. Implement minimal code to pass tests (Green).
5. Run `uv run ruff check .` and `uv run pytest` to ensure zero regressions across all test files.

---

## Useful Commands

```bash
# Run all backend tests with coverage
uv run pytest

# Run a specific test file
uv run pytest tests/test_dynamic_llm_factory.py

# Lint and check code formatting
uv run ruff check .
uv run ruff format --check .

# Start local backend with reload
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
