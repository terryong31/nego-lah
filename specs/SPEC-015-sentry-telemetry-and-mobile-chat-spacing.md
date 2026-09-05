---
id: SPEC-015
title: Industry-Standard Sentry Telemetry and Mobile Chat Layout Spacing
status: complete
priority: high
created: 2026-09-05
tags: [frontend, backend, sentry, telemetry, chat, mobile, ui]
assigned: agent
---

# Context & Objectives
1. **Sentry 429 Quota Exhaustion:** The frontend was spamming Sentry with Session Replays due to `replaysSessionSampleRate: 1.0` in development, quickly exceeding the monthly quota (50 replays/month) and triggering `HTTP 429 Too Many Requests`. Additionally, backend profiling at 100% caused thousands of rate-limited profile chunks. The objective is to bring both frontend and backend Sentry configurations to industry standards: disabling baseline session recording, using `beforeErrorSampling` to only capture replays on fatal crashes/5xx errors, reducing noise in console integration, tuning trace/profile sampling rates, and ensuring clean structured logging.
2. **Mobile Chat Layout Spacing:** On mobile devices, excessive horizontal padding (16px on `UMain` + 16px on chat inner containers + borders = ~66px total) pinched chat messages, item banners, and input prompts into a narrow column. The objective is to make the mobile chat layout edge-to-edge (`px-0 border-x-0` on mobile `UMain`) with compact `px-2.5 sm:px-4` padding.

# Acceptance Criteria
- [x] Frontend Sentry: Set `replaysSessionSampleRate: 0.0` to eliminate non-error replay ingestion.
- [x] Frontend Sentry: Use `beforeErrorSampling` on `replayIntegration` to only capture replays on critical errors (`level === 'fatal'`, unhandled crashes, or 5xx HTTP server errors).
- [x] Frontend Sentry: Add `beforeSend` to filter known harmless browser noise (e.g., `ResizeObserver`, aborted requests).
- [x] Frontend Sentry: Restrict `captureConsoleIntegration` to `['error']` only (exclude `warn` to stop Vue/i18n warnings from consuming error quotas).
- [x] Frontend Sentry: Adjust `tracesSampleRate` (0.2 in production, 1.0 in development).
- [x] Backend Sentry: Tune `traces_sample_rate` (0.2 in production, 1.0 in dev) and `profile_session_sample_rate` (0.1 in production, 0.0 in dev) to prevent profiling quota exhaustion.
- [x] Backend Sentry: Configure `LoggingIntegration` capturing `INFO` breadcrumbs and `ERROR` events.
- [x] Chat Layout (`layouts/chat.vue`): Use `px-0 sm:px-6 lg:px-8 border-x-0 sm:border-x` so mobile viewport is not doubly padded.
- [x] Chat Page (`pages/chat.vue`): Use responsive `px-2.5 sm:px-4` horizontal padding for item header, messages scroller, and prompt input.
- [x] Automated tests pass for layout and chat components.

# Technical Design & Contracts
### Frontend `sentry.client.config.ts`:
- `replaysSessionSampleRate: 0.0`
- `replaysOnErrorSampleRate: 1.0`
- `beforeErrorSampling: (event) => boolean` checking `event.level === 'fatal'`, unhandled exceptions, and 5xx status codes.
- `captureConsoleIntegration({ levels: ['error'] })`

### Backend `backend/main.py`:
- `traces_sample_rate = 0.2 if IS_PROD else 1.0`
- `profile_session_sample_rate = 0.1 if IS_PROD else 0.0`
- `LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)`

### Frontend Chat Layout & Spacing:
- `layouts/chat.vue`: `<UMain class="... px-0 sm:px-6 lg:px-8 border-x-0 sm:border-x ...">`
- `pages/chat.vue`: responsive horizontal padding `px-2.5 sm:px-4` or `px-3 sm:px-4`.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** Automated tests assert `layouts/chat.vue` renders with responsive mobile padding classes.
- [x] **Scenario 2:** Frontend vitest suite executes cleanly with new Sentry and Chat page configurations.
- [x] **Scenario 3:** Backend test suite passes without Sentry initialization regression.

# Implementation Files
- `frontend/sentry.client.config.ts` - Industry standard replay, trace, and console configuration.
- `backend/main.py` - Industry standard trace, profiling, and logging integration.
- `backend/core/telemetry.py` - Aligned backend telemetry configuration.
- `frontend/app/layouts/chat.vue` - Mobile edge-to-edge chat container layout.
- `frontend/app/pages/chat.vue` - Reduced mobile horizontal padding across item header, message list, and input bar.
- `frontend/tests/layouts/chat.test.ts` - Layout assertion verification.
- `docs/adr/0006-sentry-session-replay-and-distributed-tracing.md` - Update ADR documentation.
