# Non-Functional Audit — 2026-10-06

**Scope:** whole monorepo at `cd88de5` (backend, frontend, Supabase migrations, CI/CD, deploy config).
**Covers:** security, privacy & compliance, reliability & availability, performance, scalability, cost,
observability, disaster recovery, deployability & supply chain, maintainability, testability,
accessibility, SEO.
**Out of scope:** functional correctness of features, and anything only visible on the live
servers, dashboards or third-party consoles (Lightsail firewall, Supabase plan, Sentry settings,
Cloudflare zone). Findings that depend on those are marked **verify**.

> **Remediation (2026-10-07):** the in-repo fixes are tracked in
> [SPEC-101](../specs/SPEC-101-non-functional-audit-remediation.md), including which findings were
> left out of scope and why. This document is kept as written, as the record of what was found.

Each finding is tagged **Confirmed** (reproduced by running something), **Code-verified** (read
end to end, not executed), or **Verify** (depends on configuration outside the repo).

---

## 1. Executive summary

The codebase is unusually disciplined for its size. It has 2,942 passing tests, enforced domain
boundaries, append-only migrations applied by CI, httpOnly opaque sessions, and floor prices
protected by Postgres column grants. Ruff, ESLint, `nuxt typecheck`, bandit (production code) and
pip-audit are all clean.

The weak spots are concentrated in a few places:

- **operational edges:** what happens when Redis is slow, an upload is hostile, a table passes
  1,000 rows, or a deploy runs;
- **telemetry that collects more than it should;**
- **the frontend supply chain.**

### Fix first

| # | Finding | Category | Severity | Status |
|---|---------|----------|----------|--------|
| 1 | [SEC-1](#sec-1) Live buyer **and admin** session cookies are sent to Sentry on every backend error | Security / Privacy | **High** | Confirmed |
| 2 | [AVL-1](#avl-1) A 435 KB PNG avatar drives one worker to **1.17 GB** RSS; the container limit is 1.2 GB | Availability | **High** | Confirmed |
| 3 | [SCL-1](#scl-1) Admin chat inbox is built from the **oldest** 1,000 messages; new buyers vanish past that | Scalability | **High** | Code-verified |
| 4 | [REL-1](#rel-1) Every request depends on a synchronous Redis client with **no socket timeout**, on a 5–6-thread pool | Reliability | **High** | Code-verified |
| 5 | [SUP-1](#sup-1) 65 frontend advisories (6 critical); the CI "audit" step cannot detect any of them | Supply chain | **High** | Confirmed |
| 6 | [PRV-1](#prv-1) Sentry Replay captures API request bodies, including `/auth/login` passwords | Privacy | **High** | Verify |
| 7 | [REL-2](#rel-2) Rate limiter re-extends its window on every allowed request; honest buyers get 429s | Reliability | Medium | Confirmed |
| 8 | [SCL-2](#scl-2) `list_users()` is never paginated in production paths, so it silently caps at 50 users | Scalability | Medium | Code-verified |
| 9 | [DEP-1](#dep-1) Every backend deploy is an outage; no post-deploy health gate; docs say "zero-downtime" | Deployability | Medium | Code-verified |
| 10 | [A11Y-1](#a11y-1) Primary buttons fail contrast in light mode (2.37:1 against WCAG AA's 4.5:1) | Accessibility | Medium | Confirmed |

### Scorecard

| Area | Rating | One-line reason |
|------|--------|-----------------|
| Security | Good, with gaps | Strong auth/CSRF/RLS design; undermined by telemetry (SEC-1) and dependency drift |
| Privacy & compliance | Needs work | Session cookies, passwords and ad-consent defaults all leave the platform |
| Reliability & availability | Needs work | Redis is a silent single point of failure; uploads can OOM the box; deploys drop traffic |
| Performance | Adequate | Backend sound but blocks the loop in ~30 places; 292 KB gz entry chunk on the SPA |
| Scalability | Needs work | Several "read everything" queries with hard caps at 50 / 1,000 rows |
| Cost control | Adequate | Per-user message limit works; the token budget does not |
| Observability | Needs work | Errors are well covered; no readiness check, metrics, request IDs or log rotation in-repo |
| Disaster recovery | Undocumented | No backup, restore, RPO or RTO statement anywhere in `docs/` |
| Deployability & CI | Adequate | Good gates; unpinned actions/toolchains; no rollout safety |
| Maintainability | Good | Clear boundaries and specs; some dead infrastructure and doc drift |
| Testability | Strong | 89.9% backend coverage gated; frontend has no coverage gate, E2E or load tests |
| Accessibility | Adequate | Mostly clean under axe; contrast and a few missing labels |
| SEO | Needs work | Every route declares the homepage as canonical |

---

## 2. What was run

| Check | Result |
|-------|--------|
| `pytest` (backend, with coverage) | **1,934 passed**, coverage **89.90%** (gate 88%), 68 s |
| `ruff check .` | clean |
| `bandit -r .` (CI excludes) | 3 Low, all in `scripts/` (subprocess) |
| `pip-audit` | no known vulnerabilities |
| `vitest run` (frontend) | **1,008 passed** in 76 files, 122 s |
| `eslint .` / `nuxt typecheck` | clean / clean |
| `bun audit` | **65 advisories: 6 critical, 39 high, 17 moderate, 3 low** |
| `nuxt generate` (production mode) | builds; 200 precache entries / **6.7 MB**; entry chunk **893 KB raw / 292 KB gzip** |
| Playwright + axe-core 4 (mobile 390×844, 4× CPU, 150 ms RTT) | see PRF-3 and A11Y-1 |
| Image-decode memory probe | see AVL-1 |
| Sentry event capture probe | see SEC-1 |
| Rate-limit window probe | see REL-2 |
| Secret-pattern scan of tracked files | placeholders only (shallow clone, 50 commits) |

Reproduction scripts for every probe are summarised in [Appendix A](#appendix-a--probes).

---

## 3. Findings

### 3.1 Security

<a id="sec-1"></a>
#### SEC-1 · Session cookies are shipped to Sentry in plaintext — High · Confirmed

`backend/core/telemetry.py:52` sets `send_default_pii=True`. With that flag the FastAPI integration
attaches the request's cookies to every error event. Sentry's `EventScrubber` only redacts **exact**
key matches against its denylist (`session`, `sessionid`, `csrf_token`, …). `nl_sid`, `admin_sid`,
`nl_pkce` and `nl_csrf` match none of them.

Probe output, using the app's own init options:

```
cookies sent to Sentry: {'nl_sid': 'SESSION-ID-SECRET', 'admin_sid': 'ADMIN-SESSION-SECRET',
                         'nl_pkce': 'PKCE-VERIFIER', 'session': '[Filtered]'}
```

**Impact:** an `admin_sid` is a post-2FA credential with a 2-hour sliding lifetime. Anyone who can
read the Sentry project (a teammate, an integration, a leaked token, or Sentry itself) can replay
it and get the full admin console, including refunds, bans and listing edits. Buyer `nl_sid`s are
30-day sessions.

**Fix:** pass `event_scrubber=EventScrubber(denylist=DEFAULT_DENYLIST + ["nl_sid", "admin_sid",
"nl_pkce", "nl_csrf", "csrf_token"])`, or drop `request.cookies` in a `before_send`. Then rotate
by flushing `admin:sess:*` and `user:sess:*`, since past events already hold live values. Add a
test asserting that a captured event carries no session cookie.

<a id="sec-2"></a>
#### SEC-2 · Unauthenticated amplification through the "test" token path — Medium · Code-verified

`backend/domains/identity/auth_middleware.py:81`: any `Authorization: Bearer <x>` whose value is
not a three-part JWT falls through to `admin_supabase.auth.get_user(token)`. That is a network call
to Supabase made with the **service-role** client. The comment calls it a fallback "for mock test
environments".

In production it lets an anonymous client turn each request into an outbound Supabase call. Each
call holds one of the 5–6 executor threads (REL-1), and the per-IP limit is 10,000/min.

**Fix:** reject non-JWT bearer tokens outside tests, gated on `ENV` or removed. Fix the tests to
mint JWTs instead.

<a id="sec-3"></a>
#### SEC-3 · Client IP comes from `CF-Connecting-IP` unconditionally — Medium · Verify

`backend/core/ip.py:22` trusts `CF-Connecting-IP` from any peer. That is only safe while the
Lightsail firewall admits nothing but Cloudflare ranges (`scripts/lockdown_lightsail_firewall.sh`,
SPEC-077), and nothing in the repo or the deploy asserts that it does. If ports 80/443 are open to
the world, anyone can pick their own rate-limit bucket and their own admin-login throttle key.

**Fix:** only honour the header when the immediate peer (after Caddy's `trusted_proxies`) is a
Cloudflare range, or have Caddy overwrite it. Add a deploy-time check that the firewall is locked.

#### SEC-4 · CSP is permissive and has drifted between its two copies — Low · Code-verified

- Both `frontend/public/_headers` and `nuxt.config.ts` allow `'unsafe-inline' 'unsafe-eval'` in
  `script-src`. That removes most of CSP's XSS value.
- The production policy whitelists `http://localhost:8000` and `http://127.0.0.1:8000`.
- `_headers`, which is what Cloudflare Pages actually serves, still allows
  `https://*.supabase.co wss://*.supabase.co`, which SPEC-093/094 removed from the browser.
  `nuxt.config.ts` does not. Two hand-maintained copies have already diverged.

**Fix:** generate `_headers` from one source. Drop the localhost and Supabase origins in
production. Move toward nonce/hash-based scripts, since GTM is the main reason for
`unsafe-inline`.

#### SEC-5 · Session cookie is scoped to every subdomain — Low · Code-verified

`backend/core/env.py:96` defaults all cookie domains to `.negolah.my`, so `nl_sid` and `admin_sid`
are sent to `media.negolah.my` (R2) and to any future or taken-over subdomain. Only the readable
CSRF cookie needs the parent domain. The two httpOnly session cookies only need to reach
`api.negolah.my`.

**Fix:** leave `USER_COOKIE_DOMAIN` and `ADMIN_COOKIE_DOMAIN` unset (host-only), and keep
`CSRF_COOKIE_DOMAIN=.negolah.my`.

#### SEC-6 · Raw exception text returned to clients — Low · Code-verified

Four handlers return `detail=str(e)`: `negotiation/routes.py:126,142`, `identity/admin_users.py:78`
and `console/admin_listings.py:174`. These can leak PostgREST/Supabase internals.

**Fix:** log the exception and return a generic message.

#### SEC-7 · No per-user cap on concurrent SSE streams — Low · Code-verified

`core/notifications.py` (`sse_stream`) lets one authenticated user open as many streams as the
2,000/min per-IP limit allows. Each holds a socket, a queue and a coroutine, and uvicorn runs
without `--limit-concurrency`.

**Fix:** cap streams per user (for example 5), evicting the oldest.

---

### 3.2 Privacy & compliance

<a id="prv-1"></a>
#### PRV-1 · Session Replay records API request bodies, passwords included — High · Verify

`frontend/sentry.client.config.ts:33` sets `networkCaptureBodies: true`, with
`networkDetailAllowUrls` covering `https://api.negolah.my`. `maskAllInputs` masks the **DOM**, not
the network log. A `POST /auth/login` body (`{email, password}`), password-change and delete-account
bodies (`current_password`), and shipping addresses and phone numbers are therefore eligible for
capture. Replay records 5% of sessions and buffers 100% of sessions that error.

**Fix:** set `networkCaptureBodies: false`, or add `networkDetailDenyUrls` for `/auth/*` and
`/user/*` plus a `beforeAddRecordingEvent` that drops bodies. Then open a recorded replay of a
login in Sentry to confirm.

#### PRV-2 · Advertising consent is granted by default, with no notice — Medium · Code-verified

`frontend/app/plugins/analytics.client.ts:36-41` sets `ad_storage`, `ad_user_data` and
`ad_personalization` to `granted` before any user interaction. The code comment cites "no
GDPR/UK exposure". Malaysia's PDPA 2010 (as amended 2024) still requires notice and consent for
processing personal data, and ad personalisation is not needed to measure a storefront. Also, every
`page_view` sends `to.fullPath`, so query strings such as `/checkout/success?session_id=cs_…`
reach Google.

**Fix:** default `ad_*` to `denied` (keep `analytics_storage` if the privacy policy covers it). Send
`to.path` instead of `fullPath`.

#### PRV-3 · Account deletion leaves data and a live session behind — Medium · Code-verified

`DELETE /user/{id}` (`identity/routes.py:323`) emits `user.deleted`, deletes `user_profiles`,
`chat_settings` and `messages`, and deletes the auth user. It does **not**:

- destroy the `nl_sid` session or clear the cookies. It only invalidates a bearer token. The
  deleted user's session keeps resolving until the next token refresh fails, so new rows can still
  be written for a user who no longer exists.
- delete uploaded avatars in `images/avatars/<user_id>/`, which sit in a **public** bucket and
  are usually a face photo.
- touch `archive.conversations`. SPEC-098's own migration notes that deleted users' pre-2026-09
  transcripts remain there indefinitely.

**Fix:** call `clear_session_cookies` in the handler, remove the avatar prefix from storage, and
purge or anonymise `archive.conversations` rows for the user. State the retention of `orders` PII
(name, phone, address) in the privacy policy.

#### PRV-4 · `sendDefaultPii: true` on both SDKs — Low · Code-verified

This sends IP addresses and (backend) user identifiers with every event. Once SEC-1 and PRV-1 are
fixed this is a policy decision, but document it in the privacy policy.

---

### 3.3 Reliability & availability

<a id="avl-1"></a>
#### AVL-1 · Decompression bomb through the avatar upload — High · Confirmed

`core/images.py:98-99` runs `exif_transpose()` and `load()`, a full decode, **before** checking
dimensions. Pillow only *warns* below 179 M pixels. A 12,000 × 12,000 single-colour PNG compresses
to **445 KB**, well under the 8 MB avatar limit:

```
payload=445030B seconds=2.22 rss_before=45MB peak=1170MB
```

Any signed-in buyer can send this to `PUT /user/{id}` (`identity/routes.py:272`). The backend
container's `mem_limit` is `1200m` for **both** workers (`docker-compose.yml`), so one request
OOM-kills the container. The listing upload paths share the code but are admin-only.

**Fix:** set `Image.MAX_IMAGE_PIXELS` to around 40 M and turn `DecompressionBombWarning` into an
error. Reject on `src.size` before `exif_transpose` and `load`. Use `Image.draft()` for JPEG.
Optionally run normalisation in a subprocess with an rlimit.

<a id="rel-1"></a>
#### REL-1 · Redis on the hot path: no timeouts, and a tiny thread pool — High · Code-verified

Three properties combine:

1. **Every request makes several synchronous Redis round trips.** The pre-routing IP limiter
   (`core/rate_limit_middleware.py`) does GET + INCR + EXPIRE. Session resolution and the ban
   check add more. Production Redis is a remote managed service (Upstash, per `docker-compose.yml`).
2. **The sync client has no `socket_timeout` or `socket_connect_timeout`**
   (`core/cache.py:225`). A network stall blocks the calling thread indefinitely.
3. **All of this runs through `asyncio.to_thread`** (75 call sites) on the loop's default executor.
   That executor is `min(32, cpu_count + 4)` = **5–6 threads per worker** on a 1–2 vCPU Lightsail
   box. The comment at `core/env.py:42` sizes the Redis pool for "the ~32-thread pool", which is
   not what runs.

**Consequences:**

- A Redis brown-out freezes the whole API, because every request waits on a thread that never
  returns.
- A Redis error raises out of `IPRateLimitMiddleware`, which has no `try`, so a Redis outage is a
  500 on every route, including the public storefront.
- At startup, Redis being unreachable silently swaps in `_InMemoryRedis` for the life of the
  process (`core/cache.py:236`). Sessions, CSRF tokens, rate limits and the LLM lease then become
  per-worker: buyers are randomly logged out and CSRF checks fail, depending on which worker
  answers. Only a warning is logged.

**Fix:**

- Set `socket_timeout` and `socket_connect_timeout` (around 1 s) and `health_check_interval`.
- Install a sized default executor in the lifespan (`loop.set_default_executor(
  ThreadPoolExecutor(32))`), or move to `redis.asyncio`.
- Decide a failure policy per use. The rate limiter should fail open on a Redis error. Sessions
  should fail closed, with a clear 503.
- Refuse to start in production on the in-memory fallback.

<a id="rel-2"></a>
#### REL-2 · Rate-limit window slides forward on every allowed request — Medium · Confirmed

`core/cache.py:327-348` runs `INCR` then `EXPIRE key window` on **every** allowed request, so the
TTL keeps being pushed out and the counter only resets after `window` seconds of silence. Probe of
the chat limiter (10 / 60 s), sending one message every 7 s (8.6/min):

```
ok ok ok ok ok ok ok ok ok ok 429 429 429 429
```

The same function backs the per-IP limits, the admin-login throttle and the OTP throttle. There is
also a GET-then-INCR race that lets concurrent requests overshoot.

**Fix:** a single Lua script, or `INCR` followed by `EXPIRE … NX` (Redis 7), so the TTL is set
once per window and the check and increment are atomic.

#### REL-3 · Transient refresh failures sign buyers out — Low · Code-verified

`identity/user_session.py:161` revokes the session on **any** exception from
`refresh_session`, including timeouts and 5xx responses where the refresh token was never
consumed. A Supabase Auth blip therefore signs out every buyer whose hourly token expires during
it.

**Fix:** revoke only on an auth error (400/401 `invalid_grant`). On a transport error, keep the
session and let the request retry.

#### REL-4 · LLM failover only happens before a turn starts — Medium · Code-verified

`negotiation/llm_factory.py`:

- **The health probe is cached for 30 s** (`PROBE_CACHE_TTL`). For up to 30 s after the laptop or
  tunnel drops, turns that win the lease are routed to a dead endpoint. With `max_retries=1` they
  fail with "Something went wrong" instead of overflowing to Gemini.
- **The provider is pinned for the whole turn,** so there is no mid-turn fallback.
- **`LEASE_TTL_SECONDS = 45` is shorter than `LOCAL_READ_TIMEOUT = 120`** and the 180 s turn
  deadline. A slow local turn loses its lease and a second stream starts on the same M5, which is
  the throughput collapse the lease exists to prevent. SPEC-037 makes the *release* safe; nothing
  renews the lease.

**Fix:**

- On a connect or first-token failure from the local model, retry the turn once on Gemini and
  write `"0"` to the probe cache.
- Renew the lease from a background task while generation runs, using compare-and-`PEXPIRE` with
  the owner token.

#### REL-5 · Detached turns and SSE streams are cut on every restart — Low · Code-verified

`_running_turns` (`negotiation/routes.py:176`) is never drained in the lifespan. SIGTERM therefore
cancels in-flight agent turns, and Docker's 10 s stop timeout then SIGKILLs the open SSE streams.
Combined with DEP-1, every deploy loses whatever is mid-generation.

**Fix:** in the lifespan's shutdown, wait (bounded, about 20 s) for `_running_turns`, and set
`stop_grace_period` in compose.

---

### 3.4 Performance

#### PRF-1 · Event-loop blocking in `async def` code — Medium · Code-verified

An AST scan found **30 direct synchronous I/O calls** inside `async` functions. The ones that matter:

| Where | What blocks the loop |
|-------|----------------------|
| `identity/admin_session.py:323-338` `verify_admin` | 3 Redis calls on **every** admin request |
| `negotiation/llm_factory.py:205,219,305,339` | Redis probe cache, lease acquire and release on every chat turn |
| `negotiation/bot.py:220,237` `transfer_to_human` | Supabase upsert and an Auth admin lookup inside an agent tool |
| `catalog/items.py:256,286` | Supabase insert and select in the listing upload |

With a remote Redis, each call stalls every connection on that worker, SSE streams included, for
one network round trip.

**Fix:** wrap these in `asyncio.to_thread` (after REL-1 sizes the pool), or move to
`redis.asyncio`. Add the scan from Appendix A to `test_domain_boundaries.py`-style CI so the rule
in SPEC-023 is enforced, not conventional.

#### PRF-2 · Per-request client construction and dead startup work — Low · Code-verified

- `new_user_client()` builds a whole Supabase client (auth, PostgREST, storage and functions HTTP
  clients) per login, register and refresh, so there is no connection reuse.
- `init_db_pool()` opens an asyncpg pool in every worker, but **nothing in the codebase acquires a
  connection from it**.
- The slowapi `Limiter` is still instantiated against Redis although no route uses it any more
  (SPEC-077).

**Fix:** reuse one anon client for unauthenticated auth calls, which are stateless when no session
is stored. Delete the unused pool and the slowapi wiring.

<a id="prf-3"></a>
#### PRF-3 · Frontend boot cost — Medium · Confirmed

Production build, static server, Chromium emulating a mid-range phone (4× CPU slowdown, 150 ms RTT,
about 9 Mbps). Bytes are decoded sizes; Cloudflare's compression lowers transfer but not parse cost.

| Route | Requests | JS | CSS | FCP | LCP |
|-------|----------|----|-----|-----|-----|
| `/` | 81 | 2,021 KB | 253 KB | 3.5 s | 3.5 s |
| `/items` | 87 | 2,042 KB | 253 KB | 3.5 s | 4.9 s |
| `/login` | 89 | 2,143 KB | 253 KB | 4.1 s | 4.1 s |

The `/items` timings were measured with no backend, so API latency would add to them in production.

Contributors:

- **Entry chunk is 292 KB gzip** and is render-blocking, because without SSR nothing paints until
  it runs.
- **All three locale files are bundled eagerly** (about 75 KB raw). They are never lazy-loaded.
- **Sentry Replay and browser profiling are initialised synchronously at boot,** at roughly
  100 KB+ gzip, although only 5% of sessions record.
- **The service worker precaches 6.7 MB on first visit** (`globPatterns` includes every PNG, the
  two 320 KB `og-image` files and both hero illustrations). That is a large first-visit data cost
  for mobile users.

**Fix:**

- Use `i18n` `lazy: true` with per-locale files.
- Use `Sentry.lazyLoadIntegration('replayIntegration')` after first paint, and drop
  `browserProfilingIntegration`. It needs a `Document-Policy: js-profiling` response header, which
  neither `_headers` nor `nuxt.config.ts` sends, so today it ships code that collects nothing.
- Narrow `globPatterns` to `js,css,html,woff2` and let images be runtime-cached.
- Track a bundle budget in CI.

---

### 3.5 Scalability

<a id="scl-1"></a>
#### SCL-1 · Admin inbox is built from the oldest 1,000 messages — High · Code-verified

`GET /admin/chats` (`negotiation/admin_routes.py:164`) builds its list from
`conversation_memory.get_all_histories()` (`memory.py:294`). That function selects **every
message, ordered by `id` ascending, with no limit**. PostgREST caps responses at `max_rows`, which
is 1,000 by default (`supabase/config.toml`, and the hosted default).

Once the `messages` table passes 1,000 rows, the response holds only the **oldest** 1,000:

- conversations that started later never appear in the seller's inbox, so the human-handoff
  (HITL) path silently loses buyers;
- `last_message` and `message_count` freeze for ongoing ones.

The same handler also reads all `messages` (descending, also capped) and calls `list_users()`
(SCL-2).

**Fix:** one SQL view or RPC that returns one row per `user_id`, with the latest message, the
latest human timestamp and a count (`DISTINCT ON (user_id) … ORDER BY user_id, id DESC`), paginated.
Load a thread's messages only when it is opened.

<a id="scl-2"></a>
#### SCL-2 · Unpaginated "read everything" queries — Medium · Code-verified

- `admin_supabase.auth.admin.list_users()` is called with no `page`/`per_page` in four production
  paths: `identity/admin_users.py:37`, `identity/services.py:69`, `billing/admin_routes.py:95` and
  `negotiation/admin_routes.py:114`. GoTrue defaults to **50 per page**, so past 50 accounts:
  - the admin user list (and its ban controls) silently omits users;
  - buyer names on orders and chats fall back to email fragments;
  - the dashboard user count reads 50.

  The operator scripts in `backend/scripts/` already paginate correctly.
- Other full-table selects capped at 1,000 rows and aggregated in Python:
  - `count_conversations` (`negotiation/services.py:119`) undercounts;
  - `billing/services.py:123` (order totals for the dashboard) under-reports revenue;
  - `catalog/services.py:202`, `admin_routes` order and transaction lists.

**Fix:** paginate `list_users`. Push counts and sums into SQL (`count=exact`, or an RPC). Paginate
the admin tables.

#### SCL-3 · Single-box ceiling — Info

One 2 GB Lightsail instance runs 2 workers with about 170 MB RSS each after importing the agent,
plus Redis and Caddy, and the asyncio executor is effectively 5–6 threads per worker. That
comfortably serves the current tens of users. The first limits will be the executor (REL-1) and
memory spikes (AVL-1), not CPU. No load test exists to find the real knee (see TST-2).

---

### 3.6 Cost control

#### CST-1 · The AI token budget measures the wrong thing — Medium · Code-verified

`charge_for_turn` (`negotiation/routes.py:402-407`) charges `len(message)//4 + len(reply)//4`. The
real input of a turn includes the persona, the tool schemas, up to 20 turns of history and the
knowledge card, re-sent on every ReAct step. The 1 M tokens / 30 min ceiling
(`core/cache.py:402`) is therefore effectively unreachable. Even with every message at the
4,000-character maximum, 10 msgs/min × 30 min × about 1,200 estimated tokens is roughly 360 K.

The only working cap is 10 messages per minute per account, which is 14,400 paid turns per account
per day. Account creation is Turnstile-gated but otherwise free.

**Fix:** charge from the provider's `usage_metadata`, which `negotiation/cost.py` already prices.
Add a daily per-user and a global spend ceiling that switches to `ai_enabled=false` or Gemini
Flash-Lite. Alert on spend.

---

### 3.7 Observability

#### OBS-1 · Health, metrics and logs — Medium · Code-verified / Verify

- **`/health` returns a constant.** It does not check Redis, Supabase or the notification broker, so
  Docker's healthcheck and any uptime monitor report "healthy" during the REL-1 failure modes.
  `check_db_health()` exists and is never called. Add `/ready` that pings Redis (with a timeout)
  and reports `notification_broker.distributed`.
- **No request or correlation ID** is logged or returned. Sentry traces cover 20% of requests;
  the other 80% cannot be tied together across log lines. Add an ASGI middleware that sets
  `X-Request-ID` and binds it into `python-json-logger`.
- **No metrics:** no request rate, latency or error rate, LLM provider split, lease contention,
  Redis latency or SSE connection count outside sampled Sentry traces. Grafana is deferred in
  `TODO.md` (#58). A small Prometheus endpoint or Sentry custom metrics on those few series would
  cover most of it.
- **Logs are not rotated.** `docker-compose.yml` sets no `logging:` options, so the default
  `json-file` driver grows without limit on a small Lightsail disk unless the host's `daemon.json`
  caps it (**verify**).
- **Two logger modules** (`core/logger.py` → `nego_lah_backend`, `core/telemetry.py` → `nego_lah`)
  with different field names make log queries inconsistent.

#### OBS-2 · No alerting or uptime monitoring is defined in the repo — Low · Verify

Nothing in `docs/` names who is paged, when, or by what (uptime checks on `/` and `/health`,
Sentry alert rules, Stripe webhook failures, the payment-cleanup loop's last success). The
receipt-failure Sentry alert (SPEC-048) is the only one described.

---

### 3.8 Disaster recovery

#### DR-1 · No documented backups, restore path, RPO or RTO — Medium · Verify

`docs/` has no statement of:

- **Supabase backups:** daily backups and PITR depend on the plan; the Free plan has none.
- **Storage:** listing and avatar images in the `images` bucket are not covered by database
  backups.
- **Rebuilding the Lightsail host.** The Caddy volume holds the TLS state; the `.env` comes from
  Infisical.
- **Redis contents:** sessions and admin allowlist entries. These self-heal on login and are
  acceptable to lose, but losing them logs everyone out.
- **Rollback.** Images are tagged by SHA in GHCR, but `docker-compose.yml` pulls `:latest` and
  there is no runbook for pinning a previous SHA.

**Fix:** a one-page runbook with RPO/RTO targets, the Supabase plan's backup facts, a storage
export job, and a rollback recipe. Test a restore into staging once.

---

### 3.9 Deployability & supply chain

<a id="sup-1"></a>
#### SUP-1 · Frontend dependency advisories, and no CI gate — High · Confirmed

`bun audit` reports 65 advisories. Sorted by where they bite:

| Exposure | Packages | Notes |
|----------|----------|-------|
| **Developer machines** | `@nuxt/devtools` < 3.3.1 (**critical**: unauthenticated RPC → command execution), `simple-git`, `shell-quote` | `devtools: { enabled: true }` in `nuxt.config.ts`, so every `mise run dev` exposes it |
| **Shipped to browsers** | `@nuxtjs/mdc` 0.22.0 (**high**: URL sanitiser XSS) | Used by `<MDC>` on item descriptions (`pages/items/[id].vue:234`). Only admin-authored text, so low exploitability, but the fix is a patch bump to ≥ 0.22.1 |
| **Build / CI only** | `tar`, `undici`, `svgo`, `seroval`, `devalue`, `source-map-js`, `esbuild`, `vitest` | DoS and parsing issues in build tooling |
| **Not applicable (SSR-only)** | `nuxt` 4.4.8 payload-cache and route-rule advisories | The app is `ssr: false`; still worth the minor bump |

CI's "Dependency security audit" step runs `bun pm untrusted`. That lists packages whose
**lifecycle scripts** were blocked; it is not a vulnerability scan. The frontend therefore has no
CVE gate at all, while the backend has `pip-audit`. Renovate is configured, yet these versions are
still behind.

**Fix:** bump `nuxt`, `@nuxt/devtools`, `@nuxtjs/mdc` and `vitest`, then run `bun audit fix`. Add
`bun audit --audit-level=high` (or OSV-Scanner) to `frontend-lint`. Set `devtools.enabled` only
when explicitly opted in.

<a id="dep-1"></a>
#### DEP-1 · Deploys are outages, unverified and unpinned — Medium · Code-verified

`deploy-backend` (`.github/workflows/deploy.yml`) runs `docker compose pull && up -d` on a
**single** backend container, then `docker compose restart caddy`:

- **Recreating the only container is downtime:** tens of seconds, covering the stop timeout plus
  app start-up.
  Restarting Caddy additionally drops every open connection, including SSE.
  `docs/ci-cd/README.md` §4 describes this as a "zero-downtime rolling restart".
- **Nothing waits for the new container to become healthy.** A crash-looping image reports
  "deployed" in green.
- **The server runs `:latest`.** A rollback means hand-editing on the box.

**Fix:**

- Deploy by SHA (`BACKEND_IMAGE_TAG=${{ github.sha }}` in `.env`), then poll
  `curl -fsS https://api.negolah.my/health` and fail the job (and re-pin the previous SHA) if it
  never comes up.
- Drop the Caddy restart unless the `Caddyfile` changed. `caddy reload` is graceful.
- For real zero-downtime, run two backend replicas behind Caddy and roll them one at a time.

#### DEP-2 · Workflow hardening — Medium · Code-verified

- **Third-party actions are pinned by tag, not SHA** (`appleboy/ssh-action@v1.0.3`,
  `appleboy/scp-action@v0.1.7`, `dorny/paths-filter@v3`, `cloudflare/wrangler-action@v3`). These
  steps receive `SSH_KEY`, `INFISICAL_TOKEN` and the Cloudflare token.
- **No top-level `permissions:` block,** so jobs without one get the repository's default
  `GITHUB_TOKEN` scope.
- **Infisical is installed with `curl … | sudo -E bash`** in three jobs.
- **The `production` environment on `migrate` has no required reviewer.** A migration merged to
  `main` reaches the production database unattended.
- **Bandit is not run in CI,** although `docs/ci-cd/README.md` §5 says it is.

**Fix:** pin actions to SHAs (Renovate can maintain them), add `permissions: contents: read` at
the top, use Infisical's official action, add a reviewer to `production`, and add a `bandit` step.

#### DEP-3 · Non-reproducible toolchain — Low · Code-verified

- `uv = "latest"` and `bun = "latest"` in `mise.toml`; `setup-uv version: latest` and
  `bun-version: latest` in CI; and `COPY --from=ghcr.io/astral-sh/uv:latest` in the Dockerfile.
- Python is not pinned by mise: this audit's environment resolved **3.13**, while CI and Docker
  use **3.12**.
- `redis:alpine` is unpinned, and `caddy:2.7` is several minor releases behind.

**Fix:** pin versions in `mise.toml` and CI (and add `.python-version`), and pin image digests.

---

### 3.10 Maintainability

#### MNT-1 · Dead code and dependencies — Low · Code-verified

- **asyncpg pool:** `core/database.py` and `init_db_pool`/`close_db_pool` in the lifespan; nothing
  acquires from it (PRF-2).
- **slowapi:** `core/limiter.py`'s `Limiter`, `app.state.limiter` and the `RateLimitExceeded`
  handler; no route uses it after SPEC-077.
- **`three` and `@types/three`** are in `frontend/package.json` with no import anywhere.
- **Unused function:** `check_db_health()`.

#### MNT-2 · Hotspots and patterns — Low · Code-verified

- **Very large modules:** `negotiation/bot.py` (1,069 lines), `negotiation/routes.py` (768),
  `pages/chat.vue` (1,010), `admin/AdminChats.vue` (804).
- **Long essay-style comments** carry real knowledge but are often longer than the code they
  explain. That makes diffs and code review heavier, and much of the content duplicates the specs.
- **179 `except Exception` blocks** in production code. Many are deliberate best-effort paths, but
  together they make silent degradation the default (REL-1's in-memory fallback is one).
- **Test-only branches in production code** (SEC-2), and an `inspect.signature` check in
  `_run_turn` that appears to exist only to tolerate test doubles.

#### MNT-3 · Documentation drift — Low · Code-verified

`docs/ci-cd/README.md` describes:

- zero-downtime deploys (DEP-1);
- bandit in CI (DEP-2);
- migrations bypassing compute (CI applies them since SPEC-096);
- `NUXT_PUBLIC_SUPABASE_*` variables (removed by SPEC-093);
- "1,293+" tests (there are 1,934).

`docs/README.md` lists ADRs to 0024 and specs to 071; there are 0031 and 100. In `TODO.md`, items
1–9 are unchecked but done (ruff, CI, coverage, …).

---

### 3.11 Testability

#### TST-1 · Frontend coverage is collected, never gated — Low · Code-verified

`vitest.config.ts` configures v8 coverage, and `test:coverage` exists, but CI runs `bun run test`
with no threshold. The backend's ratchet (`fail_under = 88`) has no frontend equivalent.

#### TST-2 · No end-to-end, load or contract tests — Medium · Code-verified

- **No end-to-end tests.** Playwright is already a dev dependency (`playwright-core`), but no
  browser test covers login → chat → checkout.
- **No load test,** so REL-1, SCL-3 and the SSE fan-out have never been measured under
  concurrency.
- **No contract test** pins `docs/api/openapi.json` to the running app.

A k6 or Locust script against staging that holds about 50 SSE streams while 10 buyers chat would
have found REL-1.

---

### 3.12 Accessibility

<a id="a11y-1"></a>
#### A11Y-1 · Primary colour fails contrast in light mode — Medium · Confirmed

axe-core (WCAG 2 A/AA) on `/` and `/login`, light scheme: `color-contrast` fails at **2.37:1**,
white on `#00c16a`. That affects every primary button (Login, Submit, CTAs), the brand wordmark
and the "Forgot password" link. Dark mode passes.

**Fix:** darken `primary` in light mode to around `#007a43` (5.4:1 against white; `#008a4c` still
falls short at 4.4:1), or use dark text on the green.

#### A11Y-2 · Smaller gaps — Low · Confirmed / Code-verified

- **Item gallery `<img>` has no `alt`** (`pages/items/[id].vue:173`). It is the main product image,
  and it also lacks `width`/`height`, which causes layout shift.
- **`/login` has no `<h1>`** (axe `page-has-heading-one`).
- **Icon-only buttons:** 27 `UButton icon=` usages against 20 `aria-label`s app-wide (heuristic);
  audit the icon-only ones.

---

### 3.13 SEO

#### SEO-1 · Every route declares the homepage canonical — Medium · Code-verified

`nuxt.config.ts:69` puts `<link rel="canonical" href="https://negolah.my">` in the global head, and
no page overrides it. Crawlers that render JavaScript are told that `/items/<id>` duplicates `/`, so
listings are deindexed. Item pages are also not prerendered, and `og:url`, `og:title` and
`og:image` are global, so a shared listing link previews as the homepage.

**Fix:**

- Set `canonical` and `og:*` per route with `useHead` and `useSeoMeta`.
- Prerender `/items/*` at build time from the catalog, or serve item meta tags from a small
  Cloudflare Pages Function.
- Add `sitemap.xml`.

---

## 4. Strengths worth keeping

- **Session design.** Opaque httpOnly `nl_sid` and `admin_sid` cookies, tokens held server-side,
  single-flight refresh, and separate CSRF scopes per surface (SPEC-093).
- **Floor-price protection** at the database layer: column grants plus RLS on every table
  (SPEC-036, ADR-0009).
- **Architecture enforced by tests.** `test_domain_boundaries.py` makes the layering a build
  failure, not a convention, and `KNOWN_VIOLATIONS` is empty.
- **Migration safety.** Append-only validation, CI-applied before deploy, and guarded, idempotent
  data moves (SPEC-096, SPEC-098).
- **Request hardening.** Body size is metered on the wire, not just checked against
  `Content-Length`. Null bytes are rejected. The rate limiter runs before auth.
- **Container hygiene.** Non-root, multi-stage, healthchecked; Redis `maxmemory` set below the
  container cap.
- **Detached agent turns** survive client disconnects (SPEC-060). Payment fulfilment is idempotent
  with unique constraints.
- **Image privacy:** EXIF (including GPS) is stripped on upload.
- **Test suites:** 2,942 tests passing, 89.9% backend coverage with a ratchet, and clean
  lint/type/SAST/pip-audit results.

---

## 5. Remediation roadmap

**This week (small, high value)**

1. **SEC-1:** scrub session cookies from Sentry events, then rotate sessions.
2. **AVL-1:** pixel cap before decode.
3. **PRV-1:** stop capturing replay network bodies.
4. **SUP-1:** bump `@nuxt/devtools`/`nuxt`/`@nuxtjs/mdc`, and replace `bun pm untrusted` with
   `bun audit`.
5. **REL-2:** atomic fixed-window limiter.
6. **REL-1 (part):** Redis socket timeouts, plus a fail-open rate limiter on a Redis error.

**Next 2–4 weeks**

7. **SCL-1 / SCL-2:** inbox RPC, paginated `list_users`, SQL aggregates.
8. **REL-1 (rest):** sized executor or `redis.asyncio`; production refuses the in-memory fallback.
   **PRF-1:** add the blocking-call scan to CI.
9. **DEP-1 / DEP-2:** SHA deploys with a health gate, pinned actions, `permissions`, bandit in CI.
10. **CST-1:** charge real token usage, plus a global daily spend ceiling.
11. **PRV-2 / PRV-3:** consent defaults; complete account deletion.
12. **A11Y-1, SEO-1.**

**Later**

13. **OBS-1 / OBS-2:** `/ready`, request IDs, metrics, log rotation, alert rules.
14. **DR-1:** runbook and a restore drill.
15. **PRF-3:** lazy locales and lazy Replay; slimmer precache.
16. **TST-1 / TST-2:** frontend coverage gate, one Playwright E2E path, a k6 load test against
    staging.
17. **MNT-1 – MNT-3:** remove dead infrastructure and refresh drifted docs.

---

## Appendix A — Probes

All probes ran locally against this checkout. Nothing touched production or any external service.

- **Sentry cookie capture (SEC-1):** a minimal FastAPI app initialised with
  `send_default_pii=True` and the FastAPI integration, using a capturing `Transport`. One request
  carrying `nl_sid`, `admin_sid`, `nl_pkce` and `session` cookies hit an endpoint that raises, and
  the captured event's `request.cookies` was printed.
- **Decompression bomb (AVL-1):** a 12,000 × 12,000 RGB PNG of one colour (445 KB) was passed to
  `core.images.process_upload(max_edge=MAX_AVATAR_EDGE, max_bytes=MAX_AVATAR_IMAGE_BYTES)` in a
  fresh process. Peak RSS was read from `resource.getrusage`.
- **Rate-limit window (REL-2):** `core.cache.check_rate_limit` on the in-memory double with
  `time.time` stubbed: 14 calls 7 s apart at 10 / 60 s. The double mirrors Redis `EXPIRE`
  semantics.
- **Blocking-call scan (PRF-1):** an AST walk over every `AsyncFunctionDef` in production code
  (`tests/`, `scripts/` and `evals/` excluded). It flags calls rooted at `redis_client`,
  `admin_supabase`, `user_supabase`, `requests` or `stripe`, and known synchronous helpers, that
  are not inside a nested `def` or `lambda`.
- **Frontend lab run (PRF-3, A11Y-1):** `nuxt generate` with `NODE_ENV=production`, served
  statically. Playwright drove Chromium 390×844 with CDP CPU throttling ×4 and network emulation
  (150 ms, 1.1 MB/s down) and the service worker blocked; axe-core 4 ran with
  `wcag2a, wcag2aa, best-practice`.
