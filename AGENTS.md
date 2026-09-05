# Agent Guide - Nego-Lah Monorepo

Welcome to the **Nego-Lah** codebase. This repository contains the full-stack ecosystem for an autonomous second-hand marketplace with AI-powered price negotiations.

## Monorepo Architecture Overview

- **`/frontend`**: Nuxt 4 Single Page Application (`ssr: false`) with Nuxt UI and TailwindCSS v4, hosted on **Cloudflare Pages**.
- **`/backend`**: Modular Monolith built with FastAPI, Redis, and LangGraph/LangChain, hosted on an **AWS Lightsail** VPS instance.
- **`/specs`**: Spec-Driven Development (SDD) following the **LeanSpec** framework (<2k tokens per spec).
- **Tooling**:
  - **mise**: Polyglot version manager & task orchestrator (`mise.toml`).
  - **uv**: Ultra-fast deterministic Python packaging (`pyproject.toml` + `uv.lock`).
  - **bun**: Fast JavaScript runtime and package manager for the frontend.
  - **infisical**: Multi-environment secrets manager (`dev`, `prod`) connected to Infisical Cloud.

---

## Core Rules of Engagement for AI Agents

1. **Spec-Driven Development (LeanSpec) First:**
   - Before implementing any new feature, substantial bugfix, or architectural change, you **MUST** create or update a spec file in `/specs/SPEC-XXX-<name>.md` following the LeanSpec YAML frontmatter format.
   - Keep specs concise (<2,000 tokens) focusing on Context, Acceptance Criteria, API Contracts, and Test Scenarios.
   - Update docs by adding adr into docs/adr to document architectural decisions.

2. **Strict Test-Driven Development (TDD):**
   - **Red:** Write automated tests asserting the spec's acceptance criteria first. Verify they fail.
   - **Green:** Write the minimal implementation code to satisfy the tests. Verify they pass.
   - **Refactor:** Clean up code, enforce domain boundaries and typing, without breaking tests.

3. **Domain Boundary Discipline (Modular Monolith):**
   - In `/backend`, business logic is strictly partitioned into `domains/` (`catalog`, `negotiation`, `billing`, `identity`, `webhooks`).
   - Domains **must never** directly query or import internal tables/files of another domain. Cross-domain communication is performed solely via exported Domain Service classes.

4. **Preserve Cloudflare Pages SPA Architecture:**
   - The frontend is an SPA (`ssr: false`). Do not introduce Node/Nitro edge-only dependencies or SSR cookie dependencies. All auth is handled client-side via `@nuxtjs/supabase`.

5. **Secrets & Environment Variables:**
   - Never commit secrets or hardcoded API keys. All environment variables are injected via Infisical Cloud (`infisical run --env=dev -- ...`) or defined in typed configurations.

---

## Essential Commands (`mise`)

Run these commands from the repository root:

```bash
# Start complete local development environment (Redis + FastAPI :8000 + Nuxt :3000)
mise run dev

# Run all test suites (Backend pytest + Frontend vitest)
mise run test

# Run individual service tests
mise run test:backend
mise run test:frontend

# Lint and check code quality
mise run lint

# Typecheck frontend
mise run typecheck
```
