# 25. Edge Proxy Lockdown, Pre-Routing ASGI Rate Limiting, and Local Cryptographic JWT Verification

- Status: Accepted
- Date: 2026-09-14
- Deciders: Terry (owner), AI Agent
- Relates to: SPEC-077; closes TODO 63, 64, 65; builds on ADR 0005 (API domain), ADR 0014 (Cloudflare posture), ADR 0018 (Pre-launch security)

## Context

A security review on 2026-09-10 exposed a chained vulnerability on the API:
1. **Origin Exposure (TODO 63):** `api.negolah.my` resolved directly to an AWS Lightsail address, bypassing Cloudflare's edge WAF and DDoS mitigations. Without firewall restrictions to Cloudflare IPs, edge protections can be bypassed by hitting the origin directly.
2. **Post-Auth Rate Limiter Bypass (TODO 64):** `slowapi` decorators (`@limiter.limit`) wrapped endpoint functions. In FastAPI, route dependencies (`Depends(...)`) run before endpoint functions. Requests bearing forged tokens failed in `Depends(verify_user_token)` with 401, never reaching the limiter or incrementing rate counters. An attacker could flood the API with bogus requests without ever receiving 429. Furthermore, expensive streaming endpoints like `/chat/stream` had no per-IP limit.
3. **Uncached Supabase Network Round Trips (TODO 65):** `verify_user_token` verified tokens via `admin_supabase.auth.get_user(token)`. Valid tokens were cached in Redis, but forged tokens always missed and triggered a synchronous HTTPS call to Supabase (`GET /auth/v1/user`), risking thread starvation and upstream denial-of-service.

## Decision

1. **Cloudflare Proxying & Origin Lockdown (TODO 63):**
   - Proxy `api.negolah.my` through Cloudflare (orange-clouded, Full Strict TLS).
   - SSE connections (`/chat/stream`, `/chat/notifications/stream`) survive Cloudflare proxying via 15s ping frames and `X-Accel-Buffering: no`, safely within Cloudflare's 100s idle timeout.
   - Lock down AWS Lightsail ports 80/443 to Cloudflare published IP ranges (IPv4 & IPv6).
   - Configure Caddy with Cloudflare trusted proxies and pass `CF-Connecting-IP`.
   - Provide a unified IP resolver `core.ip.get_client_ip` prioritizing `CF-Connecting-IP`.

2. **Pre-Routing Pure ASGI Rate Limiting (TODO 64):**
   - Remove all 11 `@limiter.limit` endpoint decorators across `routes/items.py`, `routes/payment.py`, `routes/chat.py`, and `routes/user.py`.
   - Implement `IPRateLimitMiddleware` as a pure ASGI middleware (`__call__(scope, receive, send)`), placed *before* routing and dependencies, but *inside* `CORSMiddleware`.
   - Pure ASGI avoids buffering streaming SSE responses (unlike `BaseHTTPMiddleware`).
   - Rate limits are tiered coarsely for NAT safety (preventing conference WiFi lockouts while mitigating flood scripts): `/chat/stream` (300/min), `/payment/checkout` (600/min), `/chat/notifications` (2000/min), `/user` (1000/min), `/items` (6000/min), default fallback (10000/min), `/health` exempted.

3. **Local Cryptographic JWT Verification (TODO 65):**
   - Verify Supabase JWTs locally using `pyjwt`'s `jwt.PyJWKClient` against `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` (asymmetric `ES256` keys with 10m cache).
   - Support symmetric `HS256` fallback when `SUPABASE_JWT_SECRET` is configured (dev/tests).
   - Verify signatures, expiration (`exp`), and audience (`aud == "authenticated"`), extracting `sub` as `user_id`.
   - Forged or expired tokens fail in microseconds on CPU without making third-party HTTPS requests.
   - Validated tokens are cached in Redis bounded by token expiration.

## Consequences

- **Positive:**
  - Forged token floods are rejected in microseconds locally or blocked by pre-routing rate limits before touching DB or external APIs.
  - LLM inference (`/chat/stream`) and all 57 routes receive per-IP protection.
  - Streaming SSE remains smooth and unbuffered.
  - Eliminates upstream Supabase Auth network latency from the critical path of authenticated requests.
- **Negative / Operational:**
  - Origin IP firewall must be updated if Cloudflare alters its published CIDR blocks (handled via provided script).
