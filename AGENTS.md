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

The backend is a modular monolith partitioned into bounded domains under `backend/domains/` (`catalog`, `negotiation`, `billing`, `identity`, `webhooks`):
- **No cross-domain table access:** A domain must never import models or query another domain's private tables directly.
- **Use domain services:** Cross-domain communication goes through exported service classes (e.g. `CatalogService`, `BillingService`).
- **Resource constraints:** The backend runs on an AWS Lightsail instance with 2 GB RAM. Avoid heavy subprocesses or task queues like Celery — use lifespan-scoped background loops only.

---

## 4. Frontend Architecture (Cloudflare Pages SPA, No SSR)

- The frontend is a pure single-page application (`ssr: false`).
- Do not use Node/Nitro edge-only dependencies, server routes (`server/api`), or SSR-based cookie handling.
- Authentication is handled client-side via `@nuxtjs/supabase`.
- UI is built with **Nuxt UI** and **Tailwind CSS v4**. Prefer utility classes over custom CSS.

---

## 5. Secrets & Environment Variables

- Never commit secrets, service-role keys, or API tokens.
- Secrets are managed centrally and injected via Infisical Cloud (`infisical run --env=dev -- ...`).
- For local development without Infisical, use `.env.example` as a template.

---

## 6. Security Requirements

Follow [`docs/security/ANTI_PATTERNS.md`](docs/security/ANTI_PATTERNS.md):
- **CSRF on admin operations:** Every mutating endpoint under `/admin` must enforce `verify_csrf_token`.
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
```
