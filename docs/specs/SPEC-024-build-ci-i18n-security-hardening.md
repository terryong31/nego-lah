---
id: SPEC-024
title: Build Cache Optimization, Gold-Standard CI/CD, Full i18n Coverage, and Security Defense
status: completed
priority: high
created: 2026-09-05
tags: [devops, docker, ci-cd, i18n, security, middleware, fastapi, nuxt]
assigned: agent
---

# Context & Objectives
To ensure production readiness, reliability, and security for the Nego-Lah marketplace:
1. **Docker & Build Cache Optimization**: Minimize image rebuild times and adhere to CIS Docker Benchmarks by compiling Python bytecode ahead of time, using BuildKit cache mounts, pruning Docker build contexts, and running as a non-root user.
2. **CI/CD Pipeline Hardening**: Modernize GitHub Actions to gold standards with PR triggers, concurrency controls to prevent deployment stampedes, decoupled parallel test/audit jobs, and least-privilege permissions.
3. **Complete i18n Coverage & Parity**: Eliminate hardcoded strings across admin views and static routes in English, Malay, and Chinese, backed by an automated Vitest regression suite to enforce 100% key parity and prevent future leaks.
4. **Security Audits & Defense Middleware**: Integrate static analysis and dependency auditing (`pip-audit`, `bandit`, `bun pm untrusted`) into local tooling and CI, and deploy FastAPI defense middleware enforcing OWASP security headers, request body size limits, and URL sanity.

# Acceptance Criteria
- [x] **Docker & Build Times**:
  - `backend/Dockerfile` compiles bytecode at build time (`UV_COMPILE_BYTECODE=1`), uses cache mounts, and runs as an unprivileged system user (`appuser:10001`).
  - `backend/.dockerignore` and `frontend/.dockerignore` prevent cache invalidation from local test runs, logs, and artifacts.
- [x] **CI/CD Pipeline**:
  - GitHub Actions runs on both `push: [main]` and `pull_request: [main]`.
  - Concurrency group cancels redundant in-flight PR builds while queuing `main` pushes sequentially.
  - Fast, parallel jobs for `backend-ci` and `frontend-ci` run tests and security audits before gating deployment jobs.
  - Job execution is bound by explicit timeouts (15 minutes).
- [x] **i18n Coverage & Testing**:
  - Zero hardcoded English strings in Admin views (`AdminOrders`, `AdminItems`, `AdminChats`, `AdminUsers`, `AdminCharts`) and static routes (`terms`, `privacy`, `forgot-password`).
  - Exact key parity across `en.json`, `ms.json`, and `zh.json` verified by an automated Vitest test suite (`frontend/tests/i18n/coverage.test.ts`).
- [x] **Security Defense & Auditing**:
  - FastAPI mounts `SecurityHeadersMiddleware` returning OWASP-standard headers (`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`, and production `Strict-Transport-Security`).
  - FastAPI mounts `RequestDefenseMiddleware` enforcing a 10MB payload size limit (15MB for file uploads) and rejecting null-byte URL injections (`%00`).
  - `mise run audit` executes both backend and frontend vulnerability scans cleanly.
- [x] **Zero Regressions**:
  - 100% of existing unit/integration tests continue to pass in backend and frontend.

# Technical Design & Contracts
### FastAPI Defense Middleware
- Response Headers:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 0`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` (when `IS_PROD=True`)
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
  - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; sandbox`
- Body Limits:
  - Default maximum body: `10 * 1024 * 1024` bytes (10MB) -> returns HTTP 413.
  - Multipart upload route: `15 * 1024 * 1024` bytes (15MB) -> returns HTTP 413.
- URL Injections:
  - URLs containing `%00` or null bytes -> returns HTTP 400.

### Automated Test Scenarios (TDD)
- **Scenario 1 (Security Headers & Injections)**: `backend/tests/test_defense_middleware.py` verifies all headers, size limit 413 responses, and null-byte 400 responses.
- **Scenario 2 (i18n Coverage & Parity)**: `frontend/tests/i18n/coverage.test.ts` validates 1:1 key parity among `en.json`, `ms.json`, and `zh.json`, non-empty strings, and coverage of referenced keys.
- **Scenario 3 (Security Audits)**: `pip-audit`, `bandit`, and `bun pm audit` succeed without high-severity alerts.
- **Scenario 4 (Docker Build Context)**: Docker builds ignore temporary files and execute without permission errors under `appuser`.
