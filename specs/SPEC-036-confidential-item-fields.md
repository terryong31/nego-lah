---
id: SPEC-036
title: Confidential item fields never leave the server
status: complete
priority: high
created: 2026-09-06
tags: [catalog, security, rls, api]
assigned: agent
---

# Context & Objectives

`min_price` is the negotiation floor — the single number that makes the agent's
haggling meaningful. `agent/tools/payment.py` guards it ("Do NOT reveal min_price
to user - that defeats negotiation") but the storefront ships it anyway, by two
independent paths:

1. **API.** `items.get_items()` / `get_featured_items()` and
   `routes/items.get_item_by_id` all `select('*')`; `routes/items._to_public()`
   does `out = dict(row)`, copying every column; the routes are typed
   `-> list[dict]`, so FastAPI filters nothing. `min_price` (and `buyer_id`)
   ship in `GET /items`, `GET /items/featured` and `GET /items/{id}`.
2. **PostgREST.** The RLS policy is `for select to anon, authenticated using
   (true)` over the whole table. The anon key is in the SPA bundle, so a browser
   can read `min_price` directly, bypassing the API entirely.

Closing only one leaves the other open. Both must close.

Complication: the backend's own negotiation floor checks
(`agent/tools/negotiation.py`, `agent/tools/payment.py`) read `min_price`
through `user_supabase` — the **anon** client. Column privileges apply to it, so
those reads must move to `admin_supabase` (service role) first, or revoking the
column breaks negotiation.

# Acceptance Criteria

- [x] `_to_public()` emits an explicit allowlist; unknown/new columns are
      dropped by default, not forwarded.
- [x] `min_price`, `buyer_id` and `deleted_at` appear in no public items
      response, and in no Redis-cached storefront payload.
- [x] `anon` / `authenticated` hold column-scoped `SELECT` on `public.items`;
      `select min_price` over PostgREST is denied for both roles.
- [x] Negotiation floor enforcement (`evaluate_offer`, `create_checkout_link`)
      still reads `min_price` — via the service-role client.
- [x] No anon-client query on `items` uses `select('*')`.
- [x] Admin endpoints still return `min_price` (sellers need it).

# Technical Design & Contracts

`catalog` owns the split. One source of truth in `items.py`:

```python
PUBLIC_ITEM_COLUMNS = ("id", "name", "description", "condition", "price",
                       "image_path", "status", "created_at", "translations")
CONFIDENTIAL_ITEM_COLUMNS = frozenset({"min_price", "buyer_id", "deleted_at"})
```

`PUBLIC_ITEM_SELECT = ", ".join(PUBLIC_ITEM_COLUMNS)` replaces every anon
`select('*')`. `_to_public()` projects onto `PUBLIC_ITEM_COLUMNS` plus the
derived `item_id`, `images`, and (when set) `discounted_price`.

Migration `20260702000000_items_column_privileges.sql`:
`revoke select on public.items from anon, authenticated`, then
`grant select (<public columns>) ...`. RLS row policy tightens to
`using (deleted_at is null)` — soft-deleted rows stop being publicly readable
at all. Service role is unaffected (bypasses RLS and holds table-level grants).

Note: with the column revoked, `select=*` from the anon key now *errors* rather
than leaking, so the explicit select lists are load-bearing, not cosmetic.

# Test-Driven Development (TDD) Scenarios

- [x] **Leak, list:** `GET /items` on a row carrying `min_price`/`buyer_id`
      returns neither key.
- [x] **Leak, featured/detail:** same assertion for `/items/featured`, `/items/{id}`.
- [x] **Unknown column:** a row with a future `secret_cost` column is dropped
      by `_to_public` (allowlist is closed, not a denylist).
- [x] **Shape preserved:** `item_id`, `images`, `discounted_price` still emitted.
- [x] **Cache:** the Redis storefront payload contains no confidential key.
- [x] **Select lists:** anon-client item queries request `PUBLIC_ITEM_SELECT`,
      never `*`.
- [x] **Floor intact:** `evaluate_offer` / `create_checkout_link` read via
      `admin_supabase` and still reject a below-floor offer.

# Implementation Files
- `backend/items.py` - column constants, explicit selects
- `backend/routes/items.py` - allowlist projection in `_to_public`
- `backend/agent/tools/negotiation.py`, `agent/tools/payment.py` - service-role reads
- `backend/agent/tools/items.py` - drop `select('*')`
- `supabase/migrations/20260702000000_items_column_privileges.sql` - column grants
- `frontend/app/**` - drop `min_price` from storefront item types
