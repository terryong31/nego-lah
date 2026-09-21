# Agent Guide — Nego-Lah Monorepo

This repository implements an autonomous second-hand marketplace with real-time AI-driven price negotiation.

Follow the rules below to keep the codebase consistent, maintainable, and safe to change.

---

## 1. Spec-First Development (LeanSpec)

Documentation must stay lean. Long-form specs waste context and increase the chance of agents drifting from what's actually required.

1. **LeanSpec (under 2,000 tokens) only:**
   - Before writing a feature or fixing a non-trivial bug, create or update a spec file in `/docs/specs/SPEC-XXX-<name>.md`.
   - Follow the YAML frontmatter format (`id:`, `title:`, `status:`, `tags:`).
   - Keep it concise. Include only:
     - **Context & Objectives** — the problem being solved
     - **Acceptance Criteria** — checklist of required behavior
     - **Technical Design & Contracts** — routes, schemas, invariants
     - **TDD Scenarios** — what unit/integration tests will assert
     - **Implementation Files** — files expected to change
2. **Record architectural decisions as ADRs:**
   - Any architectural pivot or major design pattern gets an ADR in `/docs/adr/`.
3. **No spec, no code:**
   - Do not start implementation without a corresponding spec in `/docs/specs/`.

---

## 2. Test-Driven Development

Follow the Red-Green-Refactor cycle:
1. **Red:** Write tests asserting the spec's acceptance criteria first. Run them and confirm they fail.
2. **Green:** Write the minimal implementation needed to pass. Run the tests and confirm they pass.
3. **Refactor:** Clean up the implementation and enforce domain boundaries without breaking tests.
4. **Coverage gate:** Backend coverage is enforced at **≥88%**. Builds fail below this threshold — write tests accordingly.

---

## 3. Domain Boundary Discipline (Modular Monolith)

The backend has **three layers**, and a file's layer is its directory:

```
core/      shared infrastructure — config, cache, connectors, logging, CSRF,
           broadcast, email, bus. Imports NOTHING from domains/ or console/.
domains/   five bounded contexts. Business logic lives inside these packages.
console/   composition root: screens that genuinely need two domains at once.
           May import every domain; NO domain may import it.
```

**The domains are layered, and the layering is the point (SPEC-097, ADR-0030):**

```
identity (0)  <  catalog (1)  <  billing (2)  <  negotiation (3)
```

A domain may import **strictly below** itself and nothing else. An order needs an item, so
billing sits above catalog; the agent needs both, so negotiation sits on top and **nothing may
depend on it**. Before SPEC-097 all four imported each other — 24 cycles over 8 back-edges — which
is the difference between a modular monolith and a ball of mud wearing directory names.

- **Table ownership:** `items`→catalog · `orders`,`transactions`→billing · `messages`,`chat_settings`,`conversations`→negotiation · `user_profiles`,`admin_audit_log`→identity. **No cross-domain table access.** Every table a migration creates must appear in `TABLE_OWNER`.
- **Spell table names out.** `client.table("messages")`, never `client.table(name)` — a runtime name is invisible to the scanner, so it is rejected.
- **Downward calls go through the package:** `from domains.billing import BillingService`, never a module inside it.
- **Upward work goes through `core/bus.py`** — never an import:
  - `bus.emit("purchase.fulfilled", …)` / `bus.on(…)` — something happened and a higher domain may care. Fan-out, no return, and **a failing subscriber never reaches the emitter**.
  - `bus.ask("billing.active_negotiated_price", default, …)` / `bus.provides(…)` — a lower domain needs one fact a higher one owns. One provider; errors propagate; no provider returns the default.
  - Handlers must be **module-level**, and wiring is registered in `main.py`. A closure defined inside the registrar is a new object every call.
- **A screen that needs two domains is composition, not a domain.** It goes in `console/`. Splitting one is normal: identity keeps `/users`, `console/admin_ai.py` owns the AI toggle.
- **All of this is enforced**, not conventional: `backend/tests/test_domain_boundaries.py` AST-scans every `.table(…)` call and every import across all backend production code, and fails on a back-edge, a cycle, a domain importing `console/`, a `core/` import of either, an unowned table, or a fourth top-level layer. Only `tests/`, `scripts/`, `evals/` and `conftest.py` are exempt, by design.
- `KNOWN_VIOLATIONS` is a ratchet — currently **empty**; adding to it needs a reason.
- **Domain `__init__.py` must stay lazy.** Export routers and services via `domains/_lazy.py`'s `lazy_getattr`. Eager imports cause circular imports and drag LangChain (+430 ms, +70 MB RSS/worker) into boot.
- **Resource constraints:** 2 GB AWS Lightsail. The bus is deliberately synchronous and in-process — no Celery, no task queue. Anything slow belongs in a lifespan loop.

---

## 4. Frontend Architecture (Cloudflare Pages SPA, No SSR)

- The frontend is a pure single-page application (`ssr: false`).
- Do not use Node/Nitro edge-only dependencies, server routes (`server/api`), or SSR-based cookie handling.
- **Authentication is server-side, in FastAPI** (SPEC-093, ADR-0028). The backend brokers every
  Supabase auth call and issues an opaque `nl_sid` httpOnly cookie; the browser never holds a token
  and `@nuxtjs/supabase` is not installed. Use `useAuth()` for the session and `useApi()` for calls —
  both send `credentials: 'include'` plus the `X-CSRF-Token` double-submit header.
- **Realtime goes through the API too** (SPEC-094). The notification broker's SSE stream carries new
  messages and typing; there is no Supabase Realtime channel and no `@supabase/supabase-js` in the
  bundle. Never publish conversation content to a public channel.
- UI is built with **Nuxt UI** and **Tailwind CSS v4**. Prefer utility classes over custom CSS.

---

## 5. Secrets & Environment Variables

- Never commit secrets, service-role keys, or API tokens.
- Secrets are managed centrally and injected via Infisical Cloud (`infisical run --env=dev -- ...`).
- For local development without Infisical, use `.env.example` as a template.

---

## 6. Security Requirements

Follow [`docs/security/ANTI_PATTERNS.md`](docs/security/ANTI_PATTERNS.md):
- **CSRF on every cookie-authenticated mutation:** endpoints under `/admin` enforce `verify_csrf_token`;
  every mutating buyer endpoint enforces `verify_user_csrf_token`. Signature-authenticated webhooks
  (Stripe, Resend) are the only exemption.
- **No credential in a URL:** never accept a token or ticket in a query string. Cookies authenticate
  `EventSource` via `withCredentials`.
- **Fail-closed queries:** Never apply optional scoping (e.g. `if user_id: query.eq()`). If `user_id` is missing, reject the request.
- **Protect floor price:** Never expose `min_price` to the client API or in agent prompts. PostgreSQL column privileges enforce this at the database layer.
- **Allowlist external URLs:** Validate external links before rendering them in chat.

---

## Essential Commands (`mise`)

Run these from the repo root:

```bash
# Start everything locally (Redis + FastAPI :8000 + Nuxt :3000)
mise run dev

# Run all test suites (Pytest + Vitest)
mise run test

# Run individual test suites
mise run test:backend
mise run test:frontend

# Run linter and typechecks
mise run lint
mise run typecheck

# Check migration filenames and version uniqueness (what CI runs on a PR)
mise run db:validate
```

---

## Database Migrations (SPEC-096)

**CI applies production migrations, not you.** Merging a change under `supabase/migrations/`
to `main` runs the `migrate` job, which applies the pending files *before* the backend that
depends on them is deployed. A failed migration blocks that deploy.

- **Append-only.** An applied version is recorded in `supabase_migrations.schema_migrations`
  and never re-read, so editing a merged migration changes the repo and not the database —
  silently. CI rejects any modification, deletion or rename in that directory; add a new file.
- **Naming is a correctness rule.** `YYYYMMDDHHMMSS_lower_snake_name.sql`. The leading 14
  digits are the recorded version, so a duplicate prefix means the second file never runs.
- `mise run db:migrate:staging` rehearses against staging. `db:migrate:prod` still exists as
  **break-glass only** — routine use puts the schema ahead of what any reviewer has seen.
