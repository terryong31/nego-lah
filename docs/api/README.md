# API Reference

The complete, machine-readable contract is **[`openapi.json`](openapi.json)** (OpenAPI 3.1). It is
exported from the running app, not written by hand, and `backend/tests/test_docs.py` fails if it
drifts. After changing a route, run:

```bash
mise run docs:openapi
```

This page explains what the schema cannot: how to authenticate, and how the routes are grouped.

## Base URLs

| Environment | API | Interactive docs |
|-------------|-----|------------------|
| Production | `https://api.negolah.my` | Disabled (`docs_url`, `redoc_url` and `openapi_url` are off in production) |
| Local | `http://localhost:8000` | [`/docs`](http://localhost:8000/docs) (Swagger UI), [`/redoc`](http://localhost:8000/redoc) |

## Authentication

There are no bearer tokens in the browser. Both audiences use an opaque, `httpOnly` session cookie
whose Supabase tokens live in Redis on the server ([ADR-0028](../adr/0028-buyer-sessions-move-behind-the-api.md)).

| Audience | Session cookie | Sign in | Mutations require |
|----------|----------------|---------|-------------------|
| Buyer | `nl_sid` | `POST /auth/login`, `POST /auth/register`, or Google via `GET /auth/oauth/start` → `GET /auth/callback` | `X-CSRF-Token` header matching the CSRF cookie (double submit) |
| Admin | `admin_sid` | `POST /admin/auth/login` (password) → `POST /admin/auth/verify-2fa` (email OTP) | `X-CSRF-Token` header (`GET /admin/auth/csrf`) |

- Send requests with `credentials: 'include'`. In the SPA, `useApi()` does this and attaches the
  CSRF header.
- Server-sent event streams (`GET /chat/notifications/stream`, `GET /admin/chats/{user_id}/stream`)
  authenticate with the same cookie via `EventSource(url, { withCredentials: true })`. No route
  accepts a credential in the query string.
- `POST /auth/login`, `/auth/register`, `/auth/password/forgot` and `/admin/auth/login` require a
  Cloudflare Turnstile token in production.
- Signature-authenticated webhooks are the only unauthenticated mutations:
  `POST /payment/webhook/stripe` (`Stripe-Signature`) and `POST /webhooks/resend` (Svix).

## Route groups

| Prefix | Domain | Audience | What it covers |
|--------|--------|----------|----------------|
| `/auth` | identity | Public → buyer | Sign-in, registration, OAuth, password reset, `GET /auth/session`. |
| `/user/{user_id}` | identity | Buyer (self only) | Profile, email, password, language, account deletion. |
| `/items` | catalog | Public | Listings, featured items, item detail (never `min_price`). |
| `/chat` | negotiation | Buyer | `POST /chat/stream` sends a message and streams the agent's reply (SSE); history, unread count, read receipts, typing, the notification stream. |
| `/payment` | billing | Buyer | Checkout at the negotiated price, payment confirmation, orders; the Stripe webhook. |
| `/admin` | identity, catalog, billing, negotiation, console | Admin | Auth, listings (with AI image analysis and market valuation), orders and refunds, shipment tracking, users, the chat inbox and hand-over. |
| `/webhooks/resend` | webhooks | Resend | Inbound email relay. |
| `/health`, `/ready` | — | Monitors | Liveness; readiness (checks Redis, 503 when down). |

Buyer routes that take a `{user_id}` check it against the session and reject a mismatch; they never
fall back to an unscoped query ([anti-pattern 1.2](../security/ANTI_PATTERNS.md#anti-pattern-12-optional-user-scoping-in-service-role-operations-idor--fail-open)).

## Rate limits

Requests are counted per client IP before routing (`core/rate_limit_middleware.py`) and per user
on expensive routes such as `POST /chat/stream`. A limited request gets `429`.

## Generating a client

```bash
npx @openapitools/openapi-generator-cli generate \
  -i docs/api/openapi.json -g typescript-fetch -o /tmp/nego-lah-client
```
