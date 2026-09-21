# 28. Buyer Sessions Move Behind the API, Not Into an SSR Server

- Status: Accepted
- Date: 2026-09-18
- Deciders: Terry (owner), AI Agent
- Relates to: SPEC-093; builds on ADR 0004 (Nuxt SPA on Cloudflare Pages), ADR 0018 (pre-launch
  security remediation, which introduced the admin cookie session), ADR 0025 (local JWT verification)

## Context

The buyer's Supabase session lives in `localStorage` because `@nuxtjs/supabase` puts it there,
and because ADR 0004 committed the frontend to `ssr: false` on Cloudflare Pages — there is no
Nuxt server to hold a cookie. Any script running in the page origin can therefore read a bearer
token that is good for an hour against `api.negolah.my`, and the server cannot distinguish the
replay from the buyer.

"Move auth server-side" is usually taken to mean "adopt SSR": run Nitro, use `@supabase/ssr`,
let the Nuxt server broker the cookie. That is not the only server available here, and it is
the more expensive one.

Two facts decide this. First, the SPA makes **no** Supabase database or storage calls — every
byte of product data already goes through FastAPI, and supabase-js is used for auth plus one
realtime channel. Second, FastAPI already implements exactly the target pattern for the admin
console: an opaque session id in Redis, an httpOnly Secure cookie, a double-submit CSRF token,
and revocation by deleting a key.

## Decision

**FastAPI becomes the token handler (BFF) for the buyer app. The frontend stays a pure SPA.**

1. All Supabase auth calls move to the backend: password, PKCE OAuth, signup confirm, password
   reset, email change. The browser receives a 302 and a cookie, never a token.
2. The session is an opaque `sb_sid` in Redis holding the Supabase access and refresh tokens —
   the admin model, generalized, not a second mechanism.
3. `verify_user_token` resolves the cookie first and falls back to `Authorization: Bearer`, which
   the eval harness and the backend test-suite keep using.
4. Access-token refresh happens server-side, single-flight under a Redis lock, so parallel tabs
   cannot race Supabase's refresh-token rotation into a spurious logout.
5. CSRF protection, previously admin-only, extends to every mutating buyer endpoint. Cookies are
   sent automatically; this is the cost of the move, not an optional extra.
6. `@nuxtjs/supabase` is removed from the Nuxt build.

### Alternatives considered

- **Nuxt SSR / Nitro on Cloudflare with `@supabase/ssr`.** Rejected: it reverses ADR 0004,
  introduces a second runtime and a second deployment target, and duplicates a session broker
  FastAPI already runs — while every authenticated call still has to reach FastAPI anyway.
- **Refresh token in an httpOnly cookie, access token in JS memory only.** Cheaper, and it does
  end the persistence of a stolen token across reloads. Rejected as the end state: the access
  token is still readable by any script at the moment it is used, which is the finding itself.
- **Encrypted stateless cookie holding the refresh token.** No Redis dependency, but revocation
  stops being instant — the property the admin design was built around.
- **Leave it; rely on CSP and the existing defence-in-depth.** The CSP already carries
  `'unsafe-inline' 'unsafe-eval'` for the Vue build, so it is not a token-theft control.

## Consequences

- **Positive:** no buyer credential is reachable by script; revocation is instant and central;
  one session model for buyer and admin; the SSE ticket workaround and the token-bearing chat
  transport both collapse into "the cookie is already attached".
- **Negative / Operational:**
  - **Redis becomes load-bearing for buyer auth, and its failure mode changed twice.**
    Before this ADR, losing Redis was degraded-but-working: caches, rate limits and leases stopped
    being shared between workers, and `_create_redis_client` fell back to an in-memory double.
    Sessions now live there, so that fallback is no longer benign — each worker would answer from
    its own empty store, and one cookie would resolve on worker A and 401 on worker B. A Redis
    outage is a sign-out storm, not a slow path. The bearer fallback in `verify_user_token` does
    not help a browser, which has no token to fall back to.

    Prod then moved that Redis off the box to a managed endpoint (Upstash, `rediss://`), which
    changes the sizing argument this ADR originally made. Measured on the live database:

    | | sidecar (was, and still local dev) | managed (prod now) |
    |---|---|---|
    | `maxmemory` | 192 MB | **64 MB** |
    | `maxmemory-policy` | `volatile-ttl` | **`noeviction`** |
    | at the cap | evicts the shortest remaining TTL first | **rejects writes** |

    So the original argument — *give sessions the longest TTL in the keyspace and they evict last*
    — buys nothing in prod, because nothing evicts at all. What happens at 64 MB instead is that
    `SETEX` starts failing: no new session can be minted, no CSRF token, no rate-limit counter, no
    cached item. Reads keep working, so **the people already signed in stay signed in and nobody
    new can log in** — a better failure for the session store than silent eviction, and a worse one
    for availability. It is also a third of the memory the argument was written against, shared
    with the token→user cache, rate-limit counters, the item cache, LLM leases and admin sessions.
    At ~1.5 KB a session, 10k concurrent buyers is ~15 MB — 8% of the old budget, 23% of this one.

    That ceiling wants a monitor rather than a comment: alert on `used_memory` against `maxmemory`,
    not on evictions, because there will not be any. Connection count is a non-issue —
    `maxclients` is 30000 against the ~100 that `REDIS_MAX_CONNECTIONS=50 × WEB_CONCURRENCY=2`
    can open.

    Local development and CI are unchanged: `dev` still points at `redis://localhost:6379`, and the
    test suite never touches a real Redis at all (`conftest.py` forces the in-memory fake).
  - The highest-risk surface in the app — sign-in — is rewritten. Sequencing matters: the
    backend accepts both cookie and Bearer before the frontend stops sending Bearer.
  - Supabase email templates must point at the API callback rather than the SPA.
  - Cookies require the frontend and API to stay same-site (`negolah.my` / `api.negolah.my`).
    A preview deployment on `*.pages.dev` will not receive the cookie.

## Follow-up — SPEC-094 (accepted alongside this)

`core/broadcast.py` publishes message **content** to the Supabase Realtime topic `chat:{user_id}`,
and `useTypingChannel` subscribes with no `private: true` and no policy on `realtime.messages`.
That channel is therefore readable by anyone holding the anon key — which ships in the bundle —
who knows a target's user id. This is a confidentiality exposure independent of where the session
is stored, and arguably the more serious of the two under GDPR Art. 32. Fixing it means either
private channels with Realtime Authorization, or folding typing and `new_message` into the SSE
broker that `core/notifications.py` already runs. **Decided: the latter** — SPEC-094 folds typing
and `new_message` into the broker, which also deletes supabase-js from the frontend entirely and
removes the last reason to hand any token to JavaScript.
