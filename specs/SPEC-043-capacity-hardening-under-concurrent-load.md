---
id: SPEC-043
title: Capacity Hardening Under Concurrent Negotiation Load
status: in-progress
priority: high
created: 2026-09-07
tags: [backend, frontend, performance, capacity, concurrency, database, llm, ux, accessibility]
assigned: agent
---

# Context & Objectives

At today's traffic the negotiation pipeline works fine; a capacity read for
~100 concurrent users (~25 concurrent negotiations, rough estimate) surfaced
four independent bottlenecks, none hypothetical — each is a concrete gap in
code already shipped. None of them is fixed by relocating Redis (that idea is
shelved): three of the four don't involve Redis's *location* at all, and the
fourth is about how Redis is called, not where it runs.

1. **Gemini fallback has no bound.** `_build_gemini_model`
   (agent/llm_factory.py:344-348) sets no timeout and no `max_retries` —
   unlike the local Qwen client three lines above it, which SPEC-020
   deliberately gave a 2.0s connect / 120s read timeout. A 429 or a slow
   response on Gemini has nothing catching it beyond `chat.py`'s generic
   `except Exception` (routes/chat.py:277-284). At 100 users, nearly every
   concurrent turn overflows to Gemini (SPEC-020's lease caps local Qwen at 1
   turn/45s), so this is the path most of the traffic actually takes.
2. **Every message rewrites the whole conversation.** `ConversationMemory.add_message`
   (agent/memory.py:34-86) does `SELECT` the full `messages` jsonb array →
   append in Python → `UPDATE` the whole array back, against a `conversations`
   table keyed only by `user_id` (supabase/migrations/20260628000000_baseline_schema.sql:69-78,
   no unique/composite key — one row holds a user's *entire* history, not
   just one item's). Cost grows with conversation length, not O(1), and it's
   read-then-write, not atomic: two near-simultaneous writers (e.g. an admin
   reply from routes/admin/chats.py:85 landing mid-turn) can silently lose
   one write's message.
3. **The host is oversubscribed and undivided.** `WEB_CONCURRENCY=4`
   (Dockerfile:53) runs on a documented 1–2 vCPU / 2GB Lightsail box
   (docs/adr/0002, docs/adr/0007) alongside Caddy and Redis, none of which
   has a resource limit in docker-compose.yml — any one container can starve
   the others, and Redis has no `maxmemory`/eviction policy.
4. **Nothing sheds load, and part of the hot path still blocks the loop.**
   `slowapi` is registered (main.py:118-119) but `@limiter.limit(...)` is
   applied to zero routes. Separately, SPEC-023 moved the Supabase half of
   `verify_user_token`'s cache lookup off the event loop but left the *Redis*
   `GET` right next to it synchronous (auth_middleware.py:72), and the same
   is true of `check_rate_limit` / `check_ai_token_limit` / `track_ai_tokens`
   in routes/chat.py:142,180,290 — a gap SPEC-023 didn't cover.
5. **The buyer has no idea any of this is happening.** When `check_rate_limit`
   rejects a turn, `chat.py:183-192` writes a friendly sentence and saves it
   through `conversation_memory.add_message` as a normal **AI** message —
   a system/UX notice disguised as something the assistant said, permanently
   in the transcript. When Gemini is slow or retrying (Workstream A), nothing
   distinguishes that from ordinary "Cooking…" latency. A non-technical buyer
   can't tell "I'm sending too fast, wait a bit" from "the AI is thinking"
   from "something broke," and has no cue to slow down or wait.

# Acceptance Criteria

**A — Gemini fallback**
- [x] `_build_gemini_model` sets an explicit request timeout and bounded
      `max_retries` with backoff.
- [x] A per-turn deadline wraps `astream()` in `chat_stream`; on expiry the
      client gets one clear "still thinking, try again" SSE frame, not a
      silent hang.
- [x] A 429 / `ResourceExhausted` from Gemini is retried (bounded, e.g. once)
      before falling through to the generic error path.
- [x] Outstanding Gemini calls per worker are capped by a semaphore sized to
      real headroom, so an overflow burst queues briefly instead of firing
      every call at once.

**B — Conversation storage**
- [x] New append-only `messages` table (`id, user_id, item_id, role, content,
      source, created_at`) backs `ConversationMemory`; `add_message` becomes a
      single `INSERT`, no prior `SELECT`.
- [x] `get_history` / `get_history_page` become an indexed
      `SELECT ... ORDER BY id DESC LIMIT/OFFSET`, not "fetch everything, slice
      in Python."
- [x] `ConversationMemory`'s public method signatures are unchanged — the
      ~15 call sites across `bot.py`, `routes/chat.py`, `routes/admin/*`,
      `payment/fulfillment.py` need no edits.
- [x] Migration: backfill `messages` from `conversations.messages`, idempotent
      (re-running inserts nothing). Single cutover rather than dual-write —
      see Deviation 1. The jsonb column is left in place as the rollback
      snapshot and is **not** dropped.
- [ ] Migration applied to production (`scripts/run_migrations.py` is run by
      hand, not by CI — this is the one step that still needs a human).
- [x] A concurrent-write regression test (two `add_message` calls for the same
      `user_id` racing) proves no message is lost — the specific bug the
      current design has.

**C — Host capacity**
- [x] `docker-compose.yml` gets `cpus`/`mem_limit` (or `deploy.resources.limits`)
      on all three services so none can starve the others.
- [x] Redis gets `maxmemory` + `maxmemory-policy` (`volatile-ttl` fits — nearly
      every key here already carries a TTL) instead of unbounded growth.
- [x] `WEB_CONCURRENCY` is pinned explicitly in `docker-compose.yml` (2,
      matching the documented core count) rather than inherited from the
      Dockerfile's `:-4` fallback.
- [ ] That number confirmed by a before/after latency comparison on the real
      box. 2 is the reasoned default, not a measured one — the comparison
      needs the production host and hasn't been run.

**D — Backpressure & the rest of the blocking-call gap**
- [x] `@limiter.limit(...)` applied to `/chat/notifications/stream` (currently
      zero protection — a client can open unbounded connections), catalog
      list endpoints, and `/payment/checkout`.
- [x] The Redis half of `auth_middleware.py:72`'s token-cache lookup, and
      `check_rate_limit` / `check_ai_token_limit` / `track_ai_tokens` in
      `routes/chat.py`, run off the event loop — extending SPEC-023 to the
      call sites it didn't cover.
- [x] `redis_client`'s connection pool gets an explicit `max_connections`
      instead of the current unbounded default (cache.py:162).

**E — Frontend rate-limit & retry UX**
- [x] The hard per-user cooldown answers with `429` + `Retry-After` and a
      `retryAfterSeconds` body, which the SPA reads to drive its countdown —
      not an SSE data part, and never a chat bubble (see Deviation 2). The
      cooldown notice is never persisted through
      `conversation_memory.add_message`.
- [x] While on cooldown, `UChatPrompt` / `UChatPromptSubmit` are disabled with
      a visible countdown ("Try again in Ns") on or beside the submit
      control — not buried as a message in the transcript.
- [x] Copy is plain-language, never implies user fault, and states exactly
      what to do and for how long — no "rate limit," "429," or backend terms
      anywhere user-facing (Nielsen Norman error-message guidelines: 7th–8th
      grade reading level, specific, constructive, not the user's fault).
- [x] A softer, non-blocking cue covers Gemini running long (Workstream A's
      retry/backoff): the existing `UChatTool` "Cooking…" indicator swaps to
      a distinct "taking a little longer than usual" label past a threshold
      (~8s); the input stays enabled — this isn't the user's doing.
- [x] If Workstream A's per-turn deadline is actually hit, the transcript
      shows a dismissible, clearly-system-styled notice (matching the
      existing `USeparator` hand-over treatment, not a chat bubble) with a
      manual "Try again" action — never a silent fake AI reply.
- [x] A progressive warning appears before the hard cutoff (e.g. at message
      8 of the 10-in-60s window), so the block is never a surprise — reuses
      `get_rate_limit_remaining`.
- [x] The countdown is accessible: `role="timer"`, deadline wrapped in
      `<time datetime>`, recomputed from `Date.now()` every tick (survives
      background-tab throttling), floored at zero. The live region stays
      silent through the count and announces only at start and at
      completion — never once per second.
- [x] Input auto-re-enables and regains focus the instant the cooldown hits
      zero; no click required.
- [x] Copy ships in all three locales (en/ms/zh), matching the existing
      i18n pattern (SPEC-005, SPEC-013).

# Technical Design & Contracts

No public API contract changes in A, C, or D. B changes `conversations`'
physical storage but not `ConversationMemory`'s interface, so its callers are
unaffected — see the file list above. A–D are independently shippable and
independently testable; they don't depend on each other and can land as
separate PRs against this one spec. Suggested order: **D then A** (lowest
risk, same-day), **C** next (needs a load comparison, not just a deploy),
**B** last (highest value, highest risk — needs its own dry run against a
data snapshot before cutover). **E** ships alongside **A**, since it depends
on the same `chat_stream` turn — the SSE contract below is the seam between
them.

**E — rate-limit / retry UX contract**
- Backend: the moment `check_rate_limit` rejects a turn, `chat_stream` sends
  `{"type": "data-cooldown", "id": "cooldown", "data": {"retryAfterSeconds": N}}`
  as an AI SDK data part — the same protocol SPEC-020/041 already use for
  `data-provider`/`data-discount` — instead of today's friendly-text-as-AI-
  message path (chat.py:183-192). This case makes no conversation-memory
  write.
- The same part shape, sent proactively at message 8, carries
  `{"warning": true, "remaining": N}` for the progressive-warning case — no
  new endpoint.
- Gemini running long drives the existing `[[STATUS:...]]` / `aiStatusText`
  mechanism (a "taking longer than usual" status string) rather than a new
  channel.
- Frontend: a new `useChatCooldown()` composable (mirrors the module-scoped-
  state pattern already used by `useNotifications`/`useTypingChannel`) owns
  the countdown, the `role="timer"` region, and re-enable/refocus logic;
  `chat.vue` wires its `disabled` state into `UChatPrompt` and renders a
  small banner in the space above it — not a transcript bubble, mirroring
  how the seller hand-over notice already uses `USeparator` instead of a
  bubble.

# Test-Driven Development (TDD) Scenarios

- [x] **A1:** A Gemini call that never returns is cancelled at the configured
      deadline; the client receives one clear SSE error frame, not a hung
      connection.
- [x] **A2:** A simulated 429 from Gemini is retried once with backoff before
      surfacing an error.
- [x] **B1:** `add_message` issues exactly one `INSERT`, no `SELECT`.
- [x] **B2:** Two concurrent `add_message` calls for the same user both
      persist — neither overwrites the other.
- [x] **B3:** Backfill migration run twice against the same data produces no
      duplicate rows.
- [ ] **C1:** Under a synthetic CPU load in the backend container, Redis
      response times stay within its configured budget (measured, not
      assumed).
- [x] **D1:** `/chat/notifications/stream` rejects a client's Nth concurrent
      open connection (limit TBD) with a clear error.
- [x] **D2:** A slow synchronous Redis call in `verify_user_token` no longer
      blocks a concurrent request on the same worker (same style of ticker
      test SPEC-023 used).
- [x] **E1:** Sending the 11th message inside 60s emits `data-cooldown` with
      the correct `retryAfterSeconds`; the message is neither shown as an AI
      bubble nor written to conversation history.
- [x] **E2:** The chat input disables, shows a live countdown, and
      re-enables itself exactly when the countdown reaches zero — no reload,
      no click.
- [x] **E3:** The 8th message in a rolling 60s window triggers the
      progressive warning once; the 9th doesn't re-trigger it; the 11th
      still triggers the hard cooldown.
- [x] **E4:** The live region announces once when the cooldown starts and
      once when it ends, and zero times in between.
- [x] **E5:** A hard Workstream-A timeout renders a system-styled retry
      notice, not a chat bubble; clicking "Try again" resubmits the last
      user message.

# Implementation Decisions & Deviations

Settled against the real codebase; these depart from the plan above.

1. **No dual-write in workstream B — the two goals are mutually exclusive.**
   The plan called for dual-writing to both stores during rollout. But writing
   to `conversations.messages` *is* the read-modify-write this workstream
   exists to delete: keeping it for safety would have kept the O(n) cost and
   the lost-update race for the entire rollout window. So the cutover is
   single-step. What makes that safe is that nothing destructive happens — the
   old column is untouched and complete up to the cutover, and deployment is
   one container swap rather than a rolling fleet, so there is no window where
   two versions write different stores. Rollback is a code revert; the cost is
   that messages written after the cutover live only in `messages` (they are
   not lost, but a reverted build would not show them).

2. **The cooldown is `429` + `Retry-After`, not an SSE data part.** The plan
   said `data-cooldown`. It can't be: the rate-limit check fires before the
   stream exists, so there is no stream to put a part in. `429` +
   `Retry-After` is also the standard answer, and the header is what the
   client-side guidance says to derive a countdown from. The SPA reads it in a
   custom transport `fetch` (`fetchWithCooldown` in `chat.vue`), because the
   AI SDK's own error path surfaces a bare `Error` with no access to the
   status, headers or body — enough to say "something went wrong", never
   enough to say "wait 12 seconds". That wrapper hands the SDK a well-formed
   empty stream so the composer settles instead of hanging.
   The other two signals *are* data parts as planned: `data-cooldown-warning`
   (the early heads-up) and `data-turn-timeout` (workstream A's deadline).

3. **`data-cooldown-warning` fires on the AI-token budget too? No — only the
   per-minute limit.** The friendly "handing you to Terry" message at
   `chat.py:183` belongs to the *AI token budget*, a different limit that
   genuinely hands the conversation to a human. That one stays a real
   transcript message, because a human taking over is a real conversational
   event, not a UI state. Only the per-minute message cooldown moved out of
   the transcript.

4. **Account deletion and the admin dashboard had to move with the table.**
   Not in the plan's file list. `routes/user.py` and `routes/admin/users.py`
   delete a user's app data table by table; leaving `messages` off those lists
   would have meant a deleted account's transcript outliving the account. The
   dashboard's conversation count became "distinct authors in `messages`",
   which is what the old one-row-per-user table was counting.

5. **Untimestamped backfilled messages inherit the previous message's time,
   not the conversation's start.** The jsonb objects carry an optional
   app-written `timestamp`. Falling back to the conversation's `created_at`
   (the obvious choice) dated a closing "deal" *before* the offer it accepted.
   Read order is by `id` either way, but the column would have been telling a
   story that never happened, and it outlives the migration.

6. **Two of this spec's own changes were regressions, both found by load
   testing rather than by the test suite.** Worth recording because unit tests
   could not have caught either — both depend on the deployed topology.

   *The per-IP limits were one shared bucket.* Caddy is a separate container,
   so it reaches uvicorn from the compose bridge, not `127.0.0.1` — uvicorn's
   default `--forwarded-allow-ips`. An untrusted peer means `X-Forwarded-For`
   is ignored and every request carries Caddy's own address, so all of
   workstream D's ceilings were shared by every user on the internet. Fixed in
   the Dockerfile by trusting the bridge range specifically — **not** `*`,
   which would have made the client's own header authoritative and let anyone
   choose their own bucket. `admin_session.client_ip()` had the same bug
   independently and is now uvicorn's answer rather than a parsed header,
   closing an admin-login brute-force bypass.

   *The ceilings assumed one IP was one person.* Behind NAT it is a whole
   venue. At the original `30/minute`, the 31st person on a shared connection
   to open the app was refused; the catalog's `120/minute` would have died
   seconds into a demo. Re-sized on the assumption that one address may be
   hundreds of people, and made env-overridable.

# Verification

- Backend: 1114 passing, coverage 88.71% (floor 88%), ruff clean.
- Frontend: 873 passing across 63 files, eslint clean, `nuxt typecheck` clean.
- The migration was applied against a scratch PostgreSQL 16 with the full
  migration chain plus seeded pre-cutover data, checking: ordering preserved
  via `with ordinality`, item context inherited, empty/`null` arrays skipped,
  timestamps monotonic, re-runs inserting zero rows (twice), RLS on with zero
  policies, both indexes present, and deleting an item nulling `item_id`
  while leaving every message in place.
- `docker compose config` validates the resource limits.
- **Load tested against a production-shaped rig**: the real image, capped at
  `cpus: 1.2` / 1200 MB (a 2 vCPU box minus Caddy's and Redis's ceilings), with
  Supabase and the LLM stubbed at fixed latency so the numbers measure the box
  rather than a provider, and Sentry pointed at a local sink so its real
  per-request cost stays in the figures.

  | concurrent users | turns | p95 time-to-first-token | p95 full turn | failures |
  |---|---|---|---|---|
  | 25  | 50  | 0.89s | 2.46s | 0 |
  | 100 | 300 | 0.84s | 2.41s | 0 |
  | 250 | 750 | 2.32s | 6.42s | 0 |

  100 concurrent negotiations run at essentially the same latency as 25. The
  box starts to slow between 100 and 250 but stays correct — every turn
  completed, no timeouts, no dropped connections — which is the graceful
  degradation this spec was aiming for. Also confirmed on the rig: per-IP
  buckets are genuinely per-IP (one client exhausting its ceiling leaves
  another untouched), and 250 opens from a single NAT address no longer
  produce a single 429.

# Implementation Files
- `backend/agent/llm_factory.py` — Gemini timeout/retry, semaphore
- `backend/routes/chat.py` — per-turn deadline, 429 handling, off-loop rate/token checks, `data-cooldown` part
- `backend/agent/memory.py` — rewritten against the `messages` table
- `supabase/migrations/` — new `messages` table + backfill migration
- `backend/auth_middleware.py` — off-loop Redis token-cache lookup
- `backend/cache.py` — `max_connections` on the Redis pool, expose `get_rate_limit_remaining` to the stream handler
- `docker-compose.yml` — resource limits, Redis `maxmemory`/policy
- `backend/Dockerfile`, `backend/.env.example` — `WEB_CONCURRENCY` default
- `backend/limiter.py`, relevant route files — applied rate limits
- `frontend/app/composables/useChatCooldown.ts` — new: countdown/timer state, accessible live region
- `frontend/app/pages/chat.vue` — disabled input, cooldown banner, slow/retry indicator, retry notice
- `frontend/app/locales/{en,ms,zh}.json` — cooldown, slow-turn and retry copy
