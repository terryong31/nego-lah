# 9. Seller-Confidential Columns Enforced in Postgres, Not Just in the API

- Status: Accepted
- Date: 2026-09-06
- Deciders: Terry (owner), AI Agent
- Consulted: SPEC-036, ADR-0004

## Context

`items.min_price` is the negotiation floor: the lowest price the agent will
accept for a listing. The entire negotiation feature is premised on the buyer
not knowing it — `agent/tools/payment.py` even says so at the point where it
rejects a low offer ("Do NOT reveal min_price to user - that defeats
negotiation").

It was nevertheless readable by anyone, through two independent paths:

1. **The public API.** `items.get_items()` and `routes/items.get_item_by_id`
   selected `*`; `routes/items._to_public()` did `out = dict(row)`, copying
   every column it received; and the handlers are annotated `-> list[dict]`, so
   FastAPI applied no response-model filtering. `min_price` (and `buyer_id`)
   shipped in `GET /items`, `GET /items/featured` and `GET /items/{id}`.

2. **PostgREST.** Per ADR-0004 the frontend is a static SPA that talks to
   Supabase directly with the anon key, which is by definition public — it ships
   in the JS bundle. The RLS policy on `items` was
   `for select to anon, authenticated using (true)`, so that key could read the
   whole table, including columns the API never intended to expose.

Fixing only the API would have left path 2 open, and a reviewer with `curl` finds
either in about thirty seconds.

### Decision Drivers

- **The leak must close on both paths**, and stay closed when someone adds the
  next endpoint or the next column.
- **The server still needs the value.** The price floor is enforced server-side
  precisely so prompt injection cannot talk the agent past it; that check has to
  keep reading `min_price`.
- **Admins still need the value.** The seller sets the floor and must see it.
- **No silent re-leak.** A new column added to `items` should default to private.

## Considered Options

1. **Pydantic response models on the item routes only.**
   - Declare a `PublicItem` schema and let FastAPI filter.
   - *Rejected as insufficient:* correct as far as it goes, and it does close
     path 1 — but it says nothing about the anon key talking to PostgREST
     directly. It also leaves `min_price` sitting in the Redis storefront cache.

2. **Row-Level Security expression that hides the column.**
   - *Rejected:* RLS filters ROWS. It has no column dimension; there is no
     policy that can return a row with a column withheld.

3. **A `public_items` view with the confidential columns omitted.**
   - Grant the anon role select on the view only.
   - *Rejected, narrowly:* it works, but it adds a second object to keep in step
     with the table on every migration, and PostgREST's filtering/ordering over
     views brings its own quirks. The grant achieves the same result with less
     surface.

4. **Column-scoped `GRANT SELECT` plus an API allowlist (Chosen).**
   - `revoke select on public.items from anon, authenticated`, then re-grant
     exactly the storefront's columns. Postgres then refuses `min_price` and
     `buyer_id` to those roles wherever they are referenced.
   - In the application, `PUBLIC_ITEM_COLUMNS` in `backend/items.py` is the
     single source of truth: it forms the PostgREST select list for every
     anon-key query, and `_to_public()` projects onto it rather than copying the
     row.

## Decision

Both layers enforce the same allowlist, and the database is the backstop.

Server-side reads of `min_price` (`agent/tools/negotiation.py`,
`agent/tools/payment.py`) moved from the anon client to `admin_supabase`, the
service role, which bypasses RLS and keeps its table-wide grant. This is the
part that is easy to get wrong: before the migration those two guards read the
floor with the anon key, so revoking the column without moving them would have
disarmed the very check the column exists to feed.

The row policy also tightened from `using (true)` to `using (deleted_at is
null)`, so a soft-deleted listing is no longer publicly readable even by a query
that forgets the filter.

`deleted_at` is granted to the anon role but never published. Column privileges
in Postgres cover every reference to a column, including in a `WHERE` clause,
and every storefront query filters `.is_('deleted_at', 'null')`; revoking it
would turn those queries into permission errors while hiding nothing, since the
value is always NULL for a row the storefront can see.

## Consequences

**Positive**

- Two independent enforcement points. Compromising the API allowlist still
  leaves Postgres refusing the column, and vice versa.
- Private by default. A column added to `items` is invisible publicly until
  someone adds it to `PUBLIC_ITEM_COLUMNS` *and* to the grant. The old
  `dict(row)` had the opposite default.
- The Redis storefront cache no longer holds the floor either, because the
  cached payload is whatever the (now column-scoped) query returned.
- `backend/tests/test_items_confidential_fields.py` asserts the two lists agree,
  so they cannot drift apart unnoticed.

**Negative / risks**

- `select('*')` on the anon client is now an *error* rather than a leak. That is
  the intended failure mode — loud beats silent — but it means the explicit
  select lists are load-bearing, and a future contributor reaching for `*` will
  get a permission error rather than a warning. The constant is named and
  commented for exactly that reason.
- Two places to edit when the storefront genuinely needs a new field: the Python
  tuple and the SQL grant. The drift test converts that from a latent leak into
  a failing build.
- The migration must be applied before the code that depends on it; a deploy
  that runs the new backend against the old grants still works (it just selects
  fewer columns), which is the safe ordering.
