-- SPEC-036: stop the anon key from reading seller-confidential item columns.
--
-- The API used to be the only thing between a buyer and `min_price` (the
-- negotiation floor), and it wasn't stopping it either. But even with the API
-- fixed there is a second, independent path: the SPA ships the anon key, the
-- policy below was `using (true)` over the whole table, and PostgREST happily
-- answers `GET /rest/v1/items?select=min_price`. Fixing the API alone leaves
-- that door open.
--
-- RLS filters ROWS; it has nothing to say about COLUMNS. The column boundary is
-- a GRANT, so this migration narrows the anon/authenticated SELECT privilege to
-- the storefront's own columns. `service_role` is untouched: it bypasses RLS and
-- keeps its table-wide grant, which is how the backend still enforces the price
-- floor and how admins still see `min_price`.

-- ------------------------------------------------------------
-- 1. Column-scoped SELECT on public.items
-- ------------------------------------------------------------
-- Revoking the table-wide grant is what actually removes `min_price` and
-- `buyer_id`; the grant that follows hands back only what the storefront reads.
revoke select on public.items from anon, authenticated;

-- NOTE ON `deleted_at`: it is granted here even though it is never *published*
-- (it is absent from PUBLIC_ITEM_COLUMNS in backend/items.py). Column privileges
-- in Postgres cover every reference to a column, including in a WHERE clause —
-- and every storefront query filters `.is_('deleted_at', 'null')`. Revoking it
-- would make those queries fail with a permission error rather than hide
-- anything: the value is always NULL for a row the storefront can see.
grant select (
    id,
    name,
    description,
    condition,
    price,
    image_path,
    status,
    created_at,
    translations,
    deleted_at
) on public.items to anon, authenticated;

-- `min_price` and `buyer_id` are deliberately absent. Keep this list in sync
-- with PUBLIC_ITEM_COLUMNS + deleted_at in backend/items.py.

-- ------------------------------------------------------------
-- 2. Row policy: soft-deleted listings are not public either
-- ------------------------------------------------------------
-- Previously `using (true)`, which relied on every caller remembering to add
-- `deleted_at is null`. Now the database enforces it, so a query that forgets
-- the filter still cannot see a removed listing.
drop policy if exists "Public can read items" on public.items;
create policy "Public can read items"
    on public.items
    for select
    to anon, authenticated
    using (deleted_at is null);

-- Writes remain closed: no insert/update/delete policies exist for these roles,
-- and the backend's service role bypasses RLS entirely.
