-- SPEC-111 — `items` learns when it was last changed.
--
-- The storefront list is cached in Redis and revalidated every 30 s against a
-- fingerprint of COUNT(id) + MAX(created_at). That catches a new listing and a
-- removed one, but an edit moves neither: a price or description changed in
-- Supabase Studio (or anywhere that skips the API's cache invalidation) stayed
-- invisible for the cache's full hour. `updated_at` moves on every write, so
-- MAX(updated_at) covers inserts and edits alike.

alter table public.items
    add column if not exists updated_at timestamptz not null default now();

-- Existing rows have not been edited since anyone could tell; start them at
-- their creation time rather than at this migration's.
update public.items set updated_at = created_at;

create or replace function public.items_touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists items_touch_updated_at on public.items;
create trigger items_touch_updated_at
    before update on public.items
    for each row execute function public.items_touch_updated_at();

-- The fingerprint is read as the storefront role, which since
-- 20260702000000_items_column_privileges.sql sees only the columns it is
-- granted. `min_price` and `buyer_id` stay ungranted.
grant select (updated_at) on public.items to anon, authenticated;
