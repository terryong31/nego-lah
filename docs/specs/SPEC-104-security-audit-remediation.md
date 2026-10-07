---
id: SPEC-104
title: Security Audit Remediation (2026-10-07)
status: in-progress
priority: high
created: 2026-10-07
tags: [security, edge, identity, telemetry, agent, pwa]
assigned: agent
---

# Context & Objectives

The [2026-10-07 security audit](../audits/2026-10-07-security-audit.md) reported nine findings.
Each was checked against the code before fixing; where the audit's mechanism or impact was wrong,
the fix targets what is actually true, and the verdict is recorded here.

| ID | Verdict | Fix |
|---|---|---|
| SEC-01 | **Confirmed.** Cloudflare's IP space is shared; any tenant's zone can reach the origin. Zone-level Authenticated Origin Pulls (the audit's first remedy) uses Cloudflare's *shared* client cert and so proves "came through Cloudflare", not "came through our zone". | Origin secret header, [ADR-0032](../adr/0032-origin-authenticated-by-zone-secret-header.md) |
| SEC-02 | **Confirmed, narrower.** Caddy forwarded the client's own `CF-Connecting-IP` verbatim, so any request that reached the origin outside Cloudflare could set its rate-limit key. The CORS allow-list entry is not exploitable (CORS binds browsers, not scripts) but was wrong. | Caddy rewrites the header from `{client_ip}` |
| SEC-03 | Confirmed | Ban lookup fails closed |
| SEC-04 | **Rule dead, impact overstated.** No backend route starts with `/api/`, but a request no route matches is never handled by the worker, so nothing was cached. The rule (and the test that fed it an invented URL) misdescribed the protection. | Delete the rule; assert no rule claims the API origin |
| SEC-05 | Confirmed | Account-wide admin login ceiling |
| SEC-06 | Confirmed | Scrub credential fields from request bodies |
| SEC-07 | Confirmed | Fence and neutralise search output |
| SEC-08 | Confirmed; the client already caps at 50 (`utils/schemas.ts`) | Server enforces the same 50 |
| SEC-09 | **Mostly not true.** Every Redis write in production code carries a TTL except `payment:cleanup_queue`, which the cleanup loop drains. | Ops: Upstash storage alert; no code |

# Acceptance Criteria

- [x] SEC-01: Caddy answers 403 to a request without the zone's `X-Origin-Auth` value once `ORIGIN_AUTH_SECRET` is set; the header is stripped before the backend sees it.
- [x] SEC-01: Caddy receives only `ORIGIN_AUTH_SECRET` (`caddy.env`), not the backend's whole env file.
- [x] SEC-02: Caddy derives the client IP from `CF-Connecting-IP` only when the peer is a Cloudflare range (`client_ip_headers` + global `trusted_proxies`) and overwrites the upstream header with `{client_ip}`.
- [x] SEC-02: `CF-Connecting-IP` is not in CORS `allow_headers`.
- [x] SEC-03: `_is_user_banned` raises 503 when the lookup fails, and caches nothing; it never returns "not banned" on error.
- [x] SEC-04: No runtime-caching rule matches any URL on the API origin; the dead `/api/` rule is gone.
- [x] SEC-05: Admin login is limited per account (20 / 15 min, case-insensitive) across all IPs, checked after the per-IP limit (5) so one address cannot exhaust it.
- [x] SEC-06: `password`, `current_password`, `new_password`, `code`, `handle`, `token_hash`, `otp` are filtered from `request.data` by both the SDK scrubber's denylist and `scrub_event`; `X-Origin-Auth` is filtered from headers.
- [x] SEC-07: `web_search` wraps results in an untrusted-data fence, strips the fence tags and role/system markers from result text, and caps each snippet's length.
- [x] SEC-08: `PUT /user/{id}/profile` returns 400 for a display name over 50 characters after trimming.

# Technical Design & Contracts

**Edge (SEC-01/02).** Global `servers { trusted_proxies static <CF ranges>; client_ip_headers
CF-Connecting-IP }`. In the site: `@not_via_our_zone expression` comparing
`{http.request.header.X-Origin-Auth}` with `{env.ORIGIN_AUTH_SECRET}` → `respond 403`;
`reverse_proxy` with `header_up CF-Connecting-IP {client_ip}` and `header_up -X-Origin-Auth`. The
matcher is inert while the secret is empty, so merging cannot lock production out before the
Cloudflare Transform Rule exists. Verified against `caddy:2.7` in Docker: untrusted peer +
spoofed header → backend sees the peer IP; secret set → missing/wrong header 403, right header
proxied with the header removed.

**Deploy.** After moving the env file into place, the deploy writes `caddy.env` from the
`ORIGIN_AUTH_SECRET=` line only (empty file when unset); compose loads it for `caddy`.

**Deploy guard.** After the health check, if `caddy.env` is non-empty the deploy requests
`https://api.negolah.my/health` through Cloudflare. Caddy marks its own refusal with
`X-Origin-Check: refused`; that mark means the zone is not sending the header, so the deploy
empties `caddy.env`, recreates Caddy alone (`--no-deps`, on the deployed tag; check off) and fails
red. Any other non-200 is a `::warning::` and leaves the check on: Cloudflare answers some requests
itself (Bot Fight Mode challenges a datacenter IP with a 403 and `cf-mitigated: challenge`), and
that says nothing about the Transform Rule. The first guard keyed on a bare 403. On 2026-10-07 it
disarmed the check on a 403 nobody could attribute. Its `up caddy` also recreated the backend
without the tag, so production ran `:latest`, which the SHA-pinned deploy never pulls.

**Rollout (owner).** Create a Cloudflare API token scoped to `negolah.my` with *Transform Rules:
Edit* and *Zone: Read*, then run `CLOUDFLARE_API_TOKEN=… scripts/enable_origin_auth.sh`. It
creates the Transform Rule, stores `ORIGIN_AUTH_SECRET` in Infisical `prod:/Backend`, and never
prints the secret. Enforcement starts on the next backend deploy. `--rotate` issues a new secret.

- [x] Rollout script run (2026-10-07): rule and Infisical secret in place, values match
- [ ] The next backend deploy is green
- [ ] A `--resolve` request straight to the origin gets 403

# TDD Scenarios

- [x] Caddyfile/compose config tests: global client-IP settings, header rewrite, header strip, 403 matcher; caddy env_file; deploy writes `caddy.env` from one key.
- [x] Deploy guard, run in bash with `curl` and `sudo` stubbed: Caddy's marked 403 → check off, Caddy alone recreated on the deployed tag, exit 1; Cloudflare's own 403, an unreachable edge → warning, check on, exit 0; 200 → silent. Every `docker compose up` in the deploy pins `BACKEND_IMAGE_TAG`.
- [x] CORS preflight requesting `CF-Connecting-IP` is not allowed.
- [x] PWA: API-origin URLs (including `.png`-suffixed paths) match no rule.
- [x] `web_search` output is fenced; an injected closing fence tag in a result is neutralised; long snippets are truncated.
- [x] Profile: 51-char name → 400 and no write; padded 50-char name is stored trimmed.
- [x] Ban lookup error → 503 with `Retry-After`, nothing cached; admin account ceiling trips across IPs, ignores email case, and is not spent by one IP; Sentry body and header scrub.

# Implementation Files

- `Caddyfile`, `docker-compose.yml`, `.github/workflows/deploy.yml`, `scripts/lockdown_lightsail_firewall.sh`, `scripts/enable_origin_auth.sh`
- `backend/main.py`, `backend/core/ip.py`, `backend/domains/negotiation/tools/payment.py`, `backend/domains/identity/routes.py`
- `backend/domains/identity/auth_middleware.py`, `backend/domains/identity/admin_session.py`, `backend/core/telemetry.py`
- `backend/tests/test_user_csrf.py` — its positive path had passed only because its unpatched ban lookup crashed and failed open
- `frontend/pwa/runtime-caching.ts`
