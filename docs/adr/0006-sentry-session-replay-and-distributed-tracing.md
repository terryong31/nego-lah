# ADR 0006: Sentry Session Replay and Distributed Tracing Architecture

## Status
Accepted

## Context
Nego-Lah features an interactive e-commerce negotiation interface where users interact with AI agents in real time, upload photos, and make payments. When an error occurs—whether on the client or within the FastAPI backend—engineering needs full context:
1. What the user did on their screen (DOM clicks, navigation, typing, modals).
2. What HTTP requests were dispatched to the backend, including request and response bodies.
3. How frontend user actions map directly to backend database queries and LLM execution spans.

Without unified distributed tracing, backend exceptions cannot be correlated to client sessions, and frontend errors lack the visual context of what the user experienced.

## Decision

1. **Frontend Sentry Session Replay (`@sentry/nuxt`):**
   - Configured in `frontend/sentry.client.config.ts` using `Sentry.replayIntegration()`.
   - Used `beforeErrorSampling` callback to restrict replay uploads strictly to serious errors: fatal crashes (`event.level === 'fatal'`), unhandled exceptions (`mechanism.handled === false`), and server 5xx errors (`statusCode >= 500`). Handled form validations, 4xx, network aborts, and benign warnings are dropped.
   - Set `replaysSessionSampleRate: 0.0` across all environments to eliminate quota waste on healthy browsing sessions.
   - Set `replaysOnErrorSampleRate: 1.0` in production (and `0.0` in development to protect local developer HMR loops from consuming monthly quotas).
   - Added `beforeSend` to filter out benign browser noise (`ResizeObserver`, `AbortError`, extensions).
   - Configured `Sentry.captureConsoleIntegration({ levels: ['error'] })` to prevent Vue template warnings and missing translation notices from generating Sentry issues.
   - Enforced PII privacy in production with `maskAllText: true`, `blockAllMedia: true`, and `maskAllInputs: true`.

2. **Distributed Tracing (Frontend to Backend):**
   - Configured `tracePropagationTargets` on the client targeting `localhost`, `127.0.0.1`, and `api.negolah.my`.
   - Set `tracesSampleRate: 0.2` in production (20% sample rate, industry standard) and `1.0` in development.
   - Configured backend `backend/main.py` with matching `traces_sample_rate=0.2 if IS_PROD else 1.0` and `profile_session_sample_rate=0.1 if IS_PROD else 0.0`.
   - Configured backend `LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)` so log records appear as breadcrumbs and only errors create Sentry events.

3. **Error Reporting Hook in `useApi`:**
   - In `frontend/app/composables/useApi.ts`, any HTTP response with status `>= 500` automatically triggers `Sentry.captureMessage` / `Sentry.captureException` with request metadata, guaranteeing that backend failures trigger replay capture.

4. **Sentry CLI Tooling:**
   - Sentry CLI org/project are supplied from the environment (Infisical), never checked into this public repo.
   - Validated live replays via `sentry-cli` and Sentry REST metrics API.

## Consequences
- **Positive:**
  - Zero 429 quota exhaustion: non-error sessions and local dev reloads consume 0 replays.
  - Video replays are reserved exclusively for critical crashes and 5xx failures where visual reproduction is essential.
  - Console noise, Vue warnings, and harmless browser errors are cleanly ignored.
  - Full-stack distributed tracing and logging breadcrumbs remain intact.
- **Negative:**
  - Replays are not recorded for normal healthy sessions (intentional trade-off to stay well within free/standard tier quotas).
