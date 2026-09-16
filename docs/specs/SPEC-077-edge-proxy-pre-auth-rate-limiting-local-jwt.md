---
id: SPEC-077
title: Edge Proxy Lockdown, Pre-Routing ASGI Rate Limiting, and Local Cryptographic JWT Verification
status: completed
priority: high
created: 2026-09-14
tags: [security, cloudflare, rate-limiting, asgi, jwt, supabase, auth]
assigned: agent
---

# Context & Objectives
Items 63, 64, and 65 in `TODO.md` expose three interconnected security and denial-of-service vulnerabilities:
1. **Origin Exposure (Item 63):** `api.negolah.my` resolves directly to the AWS Lightsail IP, lacking an edge WAF and rate limiting. Without locking the Lightsail firewall to Cloudflare IP ranges, any Cloudflare DNS proxying is easily bypassed.
2. **Post-Auth Limiter Bypass (Item 64):** slowapi's `@limiter.limit` wraps endpoint functions, causing FastAPI to execute `Depends(verify_user_token)` *before* checking rate limits. 8 forged tokens yield 8 × 401 and zero 429s, triggering unthrottled HTTPS round trips to Supabase. Furthermore, 46 of 57 endpoints (including the expensive `/chat/stream` LLM endpoint) have no per-IP limit.
3. **Network-Bound JWT Verification (Item 65):** `auth_middleware.verify_user_token` calls `admin_supabase.auth.get_user(token)`. While valid tokens cache for 2 hours in Redis, forged tokens always miss and incur a blocking HTTPS round trip (`GET /auth/v1/user`), exposing the API to upstream starvation.

This spec settles all three items with edge lockdown, pure ASGI pre-routing rate limiting, and local cryptographic JWT verification.

# Acceptance Criteria
- [x] **Item 63 (Cloudflare & Origin Firewall):**
  - [x] Cloudflare DNS proxies `api.negolah.my` (Full Strict TLS mode).
  - [x] Lightsail firewall script/runbook restricts ports 80 & 443 strictly to Cloudflare's published IP ranges (IPv4 & IPv6).
  - [x] `Caddyfile` specifies Cloudflare trusted proxies and forwards `CF-Connecting-IP`.
  - [x] SSE streams (`/chat/stream`, `/chat/notifications/stream`) survive proxying with `X-Accel-Buffering: no` and 15s heartbeats within Cloudflare's 100s idle timeout.
  - [x] Client IP resolution prioritizes trusted `CF-Connecting-IP`, falling back to `request.client.host` in dev/tests.
- [x] **Item 64 (Pre-Routing ASGI Rate Limiting):**
  - [x] Remove all 11 `@limiter.limit` decorators from endpoint handlers (`routes/items.py`, `routes/payment.py`, `routes/chat.py`, `routes/user.py`).
  - [x] Implement `IPRateLimitMiddleware` as pure ASGI (`async def __call__(self, scope, receive, send)`), placed inside `CORSMiddleware` and `RequestDefenseMiddleware` but *before* routing and dependencies.
  - [x] Pure ASGI architecture ensures streaming SSE responses are never buffered.
  - [x] Forged token floods on any authenticated route trigger HTTP 429 *before* auth or DB dependencies run.
  - [x] Enforce route-tiered NAT-coarse limits:
    - `/chat/stream`: `CHAT_STREAM_RATE_LIMIT` (default: 300/min)
    - `/payment/checkout`: `CHECKOUT_LIMIT` (default: 600/min)
    - `/chat/notifications`: `NOTIFICATION_STREAM_LIMIT` (default: 2000/min)
    - `/user`: `ACCOUNT_LIMIT` (default: 1000/min)
    - `/items`: `CATALOG_LIMIT` (default: 6000/min)
    - Global fallback: `DEFAULT_RATE_LIMIT` (default: 10000/min)
    - Exemption: `/health` (Docker/Lightsail healthchecks).
  - [x] Returns HTTP 429 with `{"detail": "Rate limit exceeded. Too many requests."}` and `Retry-After` header.
- [x] **Item 65 (Local Cryptographic JWT Verification):**
  - [x] Local JWT signature verification uses PyJWT (`jwt.PyJWKClient`) against `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` (asymmetric `ES256`/`RS256` keys with 10-minute cache).
  - [x] Supports symmetric `HS256` verification if `SUPABASE_JWT_SECRET` is configured (dev/tests).
  - [x] Forged or expired tokens fail locally in microseconds without making any outbound network call to Supabase.
  - [x] Claims validated: signature, `exp`, `aud == "authenticated"`, and extracts `sub` as `user_id`.
  - [x] Successfully verified tokens remain cached in Redis (`token:<hash>` -> `user_id`) bounded by token `exp`.
  - [x] `_is_user_banned(user_id)` enforcement remains intact.

# Technical Design & Contracts
- **Client IP Resolver (`backend/core/ip.py`):**
  ```python
  def get_client_ip(scope_or_request) -> str:
      headers = dict(scope_or_request.headers if hasattr(scope_or_request, "headers") else scope_or_request.get("headers", []))
      # In scope, headers are [(b'cf-connecting-ip', b'...')]
      cf_ip = headers.get("cf-connecting-ip") or headers.get(b"cf-connecting-ip")
      if cf_ip:
          return cf_ip.decode("latin-1") if isinstance(cf_ip, bytes) else cf_ip
      # fallback to client.host / peer
      ...
  ```
- **ASGI Rate Limit Middleware (`backend/core/rate_limit_middleware.py`):**
  ```python
  class IPRateLimitMiddleware:
      async def __call__(self, scope, receive, send):
          if scope["type"] != "http" or scope.get("path") == "/health":
              return await self.app(scope, receive, send)
          client_ip = get_client_ip(scope)
          allowed, retry_after = await check_ip_rate_limit(scope["path"], client_ip)
          if not allowed:
              response = JSONResponse(
                  {"detail": "Rate limit exceeded. Too many requests."},
                  status_code=429,
                  headers={"Retry-After": str(retry_after)}
              )
              return await response(scope, receive, send)
          return await self.app(scope, receive, send)
  ```
- **Local JWT Verifier (`backend/core/jwt_auth.py`):**
  ```python
  class SupabaseJWTVerifier:
      def __init__(self, supabase_url: str, secret: str | None = None): ...
      def verify_token(self, token: str) -> dict:
          # Reads unverified header alg:
          # - If ES256/RS256: fetch signing key via PyJWKClient(jwks_url)
          # - If HS256: verify using self.secret
          # Validates exp, aud="authenticated"
          # Returns decoded payload with payload["sub"] as user_id
  ```

# Test-Driven Development (TDD) Scenarios
- [ ] **Rate Limiting Before Auth (Red -> Green):** Send requests with invalid Bearer token to `/payment/checkout` past rate limit. Assert response is 429, NOT 401, and `verify_user_token` / Supabase auth is never called.
- [ ] **Streaming Non-Buffering (Red -> Green):** Open `/chat/stream` and `/chat/notifications/stream`. Assert chunks yield immediately through `IPRateLimitMiddleware` without being buffered in memory.
- [ ] **Local JWT Validation (Red -> Green):**
  - Valid signed JWT (ES256/HS256) succeeds and yields `user_id = sub` with 0 network calls to `GET /auth/v1/user`.
  - Expired JWT raises 401 `"Token expired"` in <1ms without calling Supabase.
  - Tampered/forged JWT signature raises 401 `"Invalid token"` in <1ms without calling Supabase.
  - Wrong audience (e.g. `aud="anon"`) raises 401 without calling Supabase.
- [ ] **Client IP Extraction (Red -> Green):** Request with `CF-Connecting-IP: 203.0.113.195` resolves to `203.0.113.195` across rate limiter and admin audit logs.
- [ ] **Coverage & Regression:** Verify backend coverage remains $\ge 88\%$.

# Implementation Files
- `backend/core/ip.py` - Centralized trusted client IP resolver (`CF-Connecting-IP` priority)
- `backend/core/rate_limit_middleware.py` - Pure ASGI pre-routing rate limit middleware
- `backend/core/jwt_auth.py` - Local cryptographic Supabase JWT verification (JWKS + HS256)
- `backend/auth_middleware.py` - Delegate token verification to local JWT verifier + Redis cache
- `backend/limiter.py` - Configuration of route limits and Redis rate check helper
- `backend/main.py` - Wire `IPRateLimitMiddleware` into ASGI middleware pipeline
- `backend/routes/{items,payment,chat,user}.py` - Remove obsolete `@limiter.limit` decorators
- `backend/admin_session.py` - Update `client_ip()` to use `core.ip`
- `Caddyfile` - Add Cloudflare trusted proxy configuration
- `scripts/lockdown_lightsail_firewall.sh` - Operator script to lock down Lightsail firewall to Cloudflare CIDRs
- `backend/tests/test_ip_rate_limit_middleware.py` - Tests for ASGI pre-routing rate limiting
- `backend/tests/test_jwt_auth.py` - Tests for local asymmetric and symmetric JWT verification
