-- ============================================================
-- Soft-delete for items
-- ============================================================
-- Deleting a listing must NOT destroy buyer order history. The previous behaviour
-- hard-deleted the item row, which (via `orders.item_id ... on delete cascade`
-- plus an explicit delete in the app) wiped the buyer's order record.
--
-- Instead we mark the item deleted and filter it out of every storefront/admin
-- listing. The row stays in the table, so orders keep their live link to it and
-- still show the item name / image / condition.

alter table public.items
    add column if not exists deleted_at timestamptz;

-- Storefront and admin listings always filter to non-deleted rows; a partial
-- index keeps those queries fast.
create index if not exists items_not_deleted_idx
    on public.items (status, created_at desc)
    where deleted_at is null;
