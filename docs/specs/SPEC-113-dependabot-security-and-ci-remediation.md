---
id: SPEC-113
title: Dependabot Security Advisory & CI Remediation
status: complete
priority: high
created: 2026-11-16
tags: [security, ci, dependencies]
assigned: agent
---

# Context & Objectives

Twelve open Dependabot security alerts and multiple open Dependabot pull requests accumulated on `main`:

- **Backend (`backend/uv.lock`):** `pyasn1 <= 0.6.4` (4 high CVEs), `soupsieve <= 2.9.2` (2 high, 2 medium CVEs), and `langgraph < 1.2.14` (1 medium CVE). Single-package PRs (#60, #61) could not pass `pip-audit` independently because both `pyasn1 >= 0.6.5` and `soupsieve >= 4.0` were required together.
- **Frontend (`frontend/package.json`, `frontend/bun.lock`):** `nuxt < 4.6.4` (3 Dependabot alerts + `@nuxt/schema` / `@nuxt/vite-builder` advisories) and `node-forge <= 1.4.2` (5 high advisories via `listhen`).
- **PR #50 (`web-minor-patch`):** `@nuxt/eslint 1.17.0` flagged root comments in `privacy.vue` and `terms.vue` (`vue/no-multiple-template-root`), and Nuxt 4.6's `prefetchGroup` threw `TypeError: Invalid URL` in `chat.test.ts` and `confirm.test.ts` because `window.location` stubs lacked a readable `href` getter or leaked across tests.
- **PR #30 (`@sentry/nuxt 11.x`):** `@sentry/nuxt` v11 removed `sendDefaultPii` and `enableLogs` from `Sentry.init()`, breaking `nuxt typecheck` in `sentry.client.config.ts` and `sentry.server.config.ts`. Also, `vue-tsc 3.3.14` stopped narrowing `shippingOrder` across `<UFormField>`'s `#hint` slot in `AdminOrders.vue`.
- **Incompatible majors/minors:** TypeScript 7.0 (PR #29) breaks `@typescript-eslint/typescript-estree` (`<6.1.0`), and `python:3.15-slim` (PR #62) conflicts with CI/target Python 3.12 and lacks PyPI wheels for Rust/C extensions.

# Acceptance Criteria

- [x] `backend/pyproject.toml` and `backend/uv.lock` upgrade `pyasn1 >= 0.6.5`, `soupsieve >= 4.0`, `langgraph >= 1.2.20`, `pillow >= 13.0.0`, `stripe >= 16.0.0`, and the `api-minor-patch` dependencies so `uv run pip-audit` reports zero vulnerabilities and all Python 3.12 wheels remain available.
- [x] `frontend/package.json` and `frontend/bun.lock` upgrade `nuxt` (`~4.6.4`), `@sentry/nuxt` (`^11.9.0`), `@vitest/coverage-v8` (`^5.0.5`), `web-minor-patch` packages, and override `node-forge` (`^1.4.3`) so `bun audit --audit-level=high` passes without ignoring `node-forge`, `simple-git`, or `@simple-git/argv-parser`.
- [x] `frontend/app/pages/privacy.vue`, `frontend/app/pages/terms.vue`, and `frontend/eslint.config.mjs` move root comments into `<script setup>` and scope `vue/no-v-html` off for those two build-time legal pages so `bun run lint` passes.
- [x] `frontend/sentry.client.config.ts` and `frontend/sentry.server.config.ts` remove the removed `sendDefaultPii` and `enableLogs` options for `@sentry/nuxt` v11 compatibility, and `frontend/app/components/admin/AdminOrders.vue` preserves `shippingOrder` narrowing under `vue-tsc 3.3.14`, so `bun run typecheck` passes.
- [x] `frontend/tests/pages/chat.test.ts` and `frontend/tests/pages/confirm.test.ts` preserve a readable `window.location.href` and restore `window.location` after tests so `bun run test` passes cleanly under Nuxt 4.6.4.
- [x] `docker-compose.yml` updates Caddy to `caddy:2.10` (PR #21), `.github/workflows/deploy.yml` updates `appleboy/ssh-action` to `v1.2.5` (PR #23), and `.github/dependabot.yml` ignores incompatible `typescript` major bumps and `python` minor/major Docker bumps.

# Technical Design & Contracts

- **Backend audit & lockfile:** `uv lock --upgrade` keeps `requires-python = ">=3.12"` and resolves `pyasn1 >= 0.6.5`, `soupsieve >= 4.0`, `langgraph >= 1.2.20`, `pillow >= 13.0.0`, and `stripe >= 16.0.0`.
- **Frontend audit gate (`frontend/scripts/audit.sh`):** retains `exec bun audit --audit-level=high` (contract asserted by `backend/tests/test_ci_workflow.py`) while dropping obsolete ignores for resolved advisories (`node-forge`, `simple-git`, `@simple-git/argv-parser`).
- **Test DOM `window.location` stubbing:** `chat.test.ts` uses `try ... finally` to restore `window.location` and exposes `get href()` on the temporary stub; `confirm.test.ts`'s `stubLocation()` copies `href` and `origin` onto the spread object because `Location.prototype` getters are non-enumerable.
- **Dependabot ignores (`.github/dependabot.yml`):** preserves SPEC-103's `(ecosystem, directory)` schedule, group, and cap invariants while ignoring `typescript` semver-major and backend Dockerfile `python` semver-minor/major updates.

# TDD Scenarios

- `cd backend && uv run pip-audit` exits 0 with zero known vulnerabilities.
- `cd backend && uv run pytest` passes all backend tests (including `test_dependabot.py`, `test_ci_workflow.py`, `test_docs.py`, `test_spec_registry.py`) above the 88% coverage gate.
- `cd frontend && bun run lint`, `bun run typecheck`, `scripts/audit.sh`, and `bun run test` all pass with zero errors.
- `mise run docs:lint`, `mise run docs:prose`, and `mise run db:validate` exit 0.

# Implementation Files

- `docs/specs/SPEC-113-dependabot-security-and-ci-remediation.md`, `docs/specs/README.md`
- `backend/pyproject.toml`, `backend/uv.lock`, `docs/api/openapi.json`
- `frontend/package.json`, `frontend/bun.lock`, `frontend/scripts/audit.sh`
- `frontend/eslint.config.mjs`, `frontend/app/pages/privacy.vue`, `frontend/app/pages/terms.vue`
- `frontend/sentry.client.config.ts`, `frontend/sentry.server.config.ts`, `frontend/app/components/admin/AdminOrders.vue`
- `frontend/tests/pages/chat.test.ts`, `frontend/tests/pages/confirm.test.ts`
- `docker-compose.yml`, `.github/workflows/deploy.yml`, `.github/dependabot.yml`
