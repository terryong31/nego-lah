---
id: SPEC-037
title: Lease ownership + backend hygiene pass
status: complete
priority: high
created: 2026-09-06
tags: [platform, redis, observability, ci]
assigned: agent
---

# Context & Objectives

Six unrelated defects, grouped because each is small and none deserves its own
spec.

1. **Lease release is not ownership-checked.** `try_acquire_local_llm_lease()`
   writes `SET key "1" NX EX 45`; `release_local_llm_lease()` does a plain
   `DELETE`. If the 45s TTL expires mid-generation, worker B acquires the slot,
   then worker A's `finally` deletes B's lease — and a third worker acquires the
   laptop while B is still generating. The classic Redlock footgun: releasing a
   lease you no longer hold.
2. **`redis_client.keys(pattern)`** in `get_active_payments_for_user` and
   `get_all_pending_payments` — `KEYS` is O(N) over the whole keyspace and
   blocks the single-threaded server.
3. **`print()` for errors** in `payment/payment_state.py` — bypasses the JSON
   logger, so Stripe cleanup failures never reach the log pipeline or Sentry.
4. **`_is_unique_violation` substring-matches error text** (`"duplicate key" in
   text`), so a row whose *data* contains "already exists" is misread as a
   constraint violation. PostgREST's `APIError` carries the SQLSTATE in `.code`.
5. **No coverage floor.** `--cov` is collected but nothing fails under a
   threshold, so coverage can rot silently.
6. **`routes/admin.py` (978 lines)** and **`AdminItems.vue` (972 lines)** are
   past the point where a reader can hold them in their head.

# Acceptance Criteria

- [x] A lease holder whose TTL expired, and whose slot another worker has since
      taken, cannot delete that worker's lease.
- [x] Release is atomic (compare-and-delete in one Redis round trip), and
      degrades to a no-op — never a wrong delete — if Redis errors.
- [x] No `KEYS` call remains in `payment/payment_state.py`; scans are cursored.
- [x] `payment_state` reports failures through `logger`, not `print`.
- [x] `_is_unique_violation` reads SQLSTATE `23505` from the exception's `code`;
      text matching survives only as a fallback for errors carrying no code.
- [x] `pytest` fails when total coverage drops below the committed floor.
- [x] `routes/admin.py` and `AdminItems.vue` are each split into focused
      modules with URLs, props and behaviour unchanged.

# Technical Design & Contracts

Lease becomes token-owned:

```python
try_acquire_local_llm_lease() -> str | None   # returns the owner token
release_local_llm_lease(token: str | None) -> None
```

`SET key <uuid4 hex> NX EX 45`. Release runs a Lua CAS registered as a Redis
script — `if redis.call('get',k)==tok then return redis.call('del',k) end` — so
the get and the del cannot interleave. `resolve_provider()` returns
`(info, token)`; `hybrid_llm_session()` passes the token to `finally`.

`_is_unique_violation` prefers `getattr(err, "code", None)`; `"23505"` → True,
any *other* non-empty SQLSTATE → False (a structured code that isn't 23505 is
positive evidence it's a different error). Only a missing code falls through to
substring matching.

`routes/admin.py` → `routes/admin/` package (`auth`, `items`, `orders`, `users`,
`chat`, `stats`) re-exported through `routes/admin/__init__.py`, keeping the
`from routes.admin import router` import and every URL identical.

# Test-Driven Development (TDD) Scenarios

- [x] **Stolen lease:** A acquires, key is expired manually, B acquires;
      A's release leaves B's token in place and B still holds the slot.
- [x] **Own lease:** acquire → release with the returned token → key gone.
- [x] **Stale token:** release with a token that was never issued is a no-op.
- [x] **Redis down:** acquire returns None (fail-closed); release swallows.
- [x] **No KEYS:** a Redis double whose `.keys()` raises still lets
      `get_all_pending_payments` / `get_active_payments_for_user` return rows.
- [x] **SQLSTATE:** `code="23505"` → True; `code="23503"` with the text
      "duplicate key" → False; no code + "duplicate key" text → True.
- [x] **Regression:** the existing 1024 tests pass unchanged after both splits.

# Implementation Files
- `backend/agent/llm_factory.py` - token lease + Lua CAS release
- `backend/payment/payment_state.py` - `scan_iter`, logger
- `backend/payment/fulfillment.py` - SQLSTATE detection
- `backend/pyproject.toml` - `fail_under`
- `backend/routes/admin/` - split router package
- `frontend/app/components/admin/AdminItems*.vue` - split component
