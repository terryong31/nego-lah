---
id: SPEC-098
title: Retire the `conversations` Table — Reversibly
status: complete
priority: medium
created: 2026-09-20
tags: [backend, database, migrations, negotiation, data-safety]
assigned: agent
---

# Context & Objectives
`public.conversations` is the pre-SPEC-043 chat history: one row per user, the whole transcript in
a `jsonb` array. SPEC-043 replaced it with `public.messages` (one row per message) and deliberately
left the old table in place as the rollback path. No code has read it since. SPEC-097 gave it an
owner (negotiation) rather than dropping it, because deleting a table holding production rows is a
decision, not a refactor.

Retiring it is worth doing — an unowned, unread table with real user data is a liability — but
three things make a straight `DROP TABLE` the wrong move:

1. **The backfill was all-or-nothing.** Its guard is `where not exists (select 1 from
   public.messages)`. If a single row existed in `messages` when it ran, the entire backfill was
   skipped and `conversations` is the *only* copy.
2. **`purge_user_data` never touched it.** Account deletion removes `messages` and `chat_settings`
   rows and leaves `conversations` behind, so "user has history here and none there" is an expected
   state, not evidence of data loss. Naive row-count comparison false-positives on it.
3. **`conversations.item_id` cascades on item delete.** Deleting a listing has been silently
   removing whole conversation rows all along, so the table is not a pristine snapshot either.

Objective: get the table out of the application's reach **without destroying anything**, and make
the evidence for a later `DROP` something a human reads rather than something a migration assumes.

# Acceptance Criteria
- [x] The retirement is **reversible by one statement**. No row is deleted, no column dropped.
- [x] `conversations` leaves the `public` schema, so PostgREST no longer exposes it.
- [x] The migration **aborts** if `messages` is empty while `conversations` holds history — the
      case where the backfill never ran and this table is the only copy.
- [x] The migration **aborts** if any user present in both has *fewer* rows in `messages` than
      entries in their old array.
- [x] Expected states (purged accounts, item-cascade gaps) do **not** abort it.
- [x] A **read-only** verification script reports the picture and exits non-zero when it finds
      something a human should look at, before anything is applied.
- [x] Filename passes `mise run db:validate`; applied by CI on merge (SPEC-096), not by hand.
- [x] `TABLE_OWNER` keeps its entry — the table still exists, so it still has an owner.

# Technical Design & Contracts
**`alter table public.conversations set schema archive;`** — not `DROP`, not `RENAME`. Supabase
exposes only `public` over PostgREST, so this removes the table from the API surface while every
row, index, constraint and grant travels with it. The reverse is
`alter table archive.conversations set schema public;`.

**Guards** run in a `DO` block before the move, in the same transaction, so a failure leaves the
table exactly where it was. They target the two states that mean *stop*, and deliberately ignore
the two that mean *this is normal*:

| state | meaning | migration |
|---|---|---|
| history in `conversations`, `messages` empty | backfill never ran; only copy | **abort** |
| user in both, old array longer than new rows | partial/missing backfill | **abort** |
| user in `conversations`, none in `messages`, no `user_profiles` row | purged account | proceed |
| fewer `conversations` rows than expected | item-delete cascade | proceed |

**`scripts/verify_conversations_retirement.py`** — read-only, run against staging then production
*before* merging. Per user it reports old array length, current `messages` count and whether a
profile still exists, then classifies each as `ok`, `purged`, or `needs review`. Exit 1 on any
`needs review`.

**Phase 2 (`DROP`) is out of scope.** It is a separate migration, taken once the archived table has
sat untouched long enough to be boring. This spec only makes that decision cheap to defer.

# Test-Driven Development (TDD) Scenarios
- [x] `assess()` classifies a purged account (`old>0, new=0, has_profile=False`) as `purged`, not a problem.
- [x] `assess()` flags `old>0, new=0, has_profile=True` as `needs review`.
- [x] `assess()` flags `old > new` for a user present in both as `needs review`.
- [x] `assess()` treats `new >= old` as `ok` — messages added after the cutover are expected.
- [x] An empty snapshot is `ok` and reports the table as already unused.
- [x] The report's exit code is non-zero if and only if something is `needs review`.
- [x] The migration filename and version pass `validate_migrations`.
- [x] `conversations` remains in `TABLE_OWNER` and the boundary suite stays green.

# Implementation Files
- `supabase/migrations/20260920000000_retire_conversations_to_archive.sql` (new)
- `backend/scripts/verify_conversations_retirement.py` (new)
- `backend/tests/test_conversations_retirement.py` (new)
- `mise.toml` — `db:verify:conversations` tasks for staging and prod

# Outcome
**Executed against a real PostgreSQL 16, not reasoned about.** A throwaway container was seeded
with a stand-in schema and six scenarios run end to end:

| scenario | result |
|---|---|
| Healthy — backfilled, 10 old / 57 new | moved to `archive` |
| Backfill never ran (`messages` empty) | **aborted**, table left in `public` |
| Live account short by 28 messages (40 old / 12 new) | **aborted**, table left in `public` |
| Purged account (history, no profile, no rows) alongside a healthy user | moved — **no false positive** |
| Applied twice | second run a clean no-op, exit 0 |
| Reversed with one statement | back in `public`, 25 rows / 25 messages intact |

After the move: gone from `public` (PostgREST cannot see it), **RLS still enabled**, **both indexes
intact**, every row present.

Also run through **the exact path CI uses** — `asyncpg.execute()` of the whole file inside one
transaction, which is what `run_migrations.py` does — because the nested `$$` / `$c$` dollar quoting
behaves differently under the simple query protocol than it does in `psql`. It applied correctly,
and on the abort case the transaction rolled back cleanly with the table still in `public`.

The verification script's judgement (`assess`) is unit-tested separately: the three states that look
identical to a row count — purged account, live account with no messages, partial backfill — are
each asserted, because `user_profiles` is the only thing that tells the first two apart.

1,934 tests, 89.93% coverage, `ruff` clean.
