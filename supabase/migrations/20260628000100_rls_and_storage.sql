-- Row Level Security + Storage policies.
--
-- Security model:
--   * The browser only ever READS data, and only the `items` table + storage.
--   * Every write goes through the FastAPI backend using the service role key,
--     which BYPASSES RLS entirely. So no insert/update/delete policies are
--     needed for the anon/authenticated roles anywhere.
--   * Clients may NOT write to the storage bucket - read only.

-- ------------------------------------------------------------
-- items: public read-only
-- ------------------------------------------------------------
alter table public.items enable row level security;

drop policy if exists "Public can read items" on public.items;
create policy "Public can read items"
    on public.items
    for select
    to anon, authenticated
    using (true);
-- No write policies => anon/authenticated cannot insert/update/delete.
-- The backend's service role bypasses RLS for all writes.

-- ------------------------------------------------------------
-- Everything else: service-role only (RLS on, zero policies)
-- ------------------------------------------------------------
alter table public.orders          enable row level security;
alter table public.transactions    enable row level security;
alter table public.conversations   enable row level security;
alter table public.chat_settings   enable row level security;
alter table public.user_profiles   enable row level security;
-- (no policies => anon/authenticated have no access; service role bypasses RLS)

-- ------------------------------------------------------------
-- Storage: 'images' bucket is public-read, client-write denied
-- ------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('images', 'images', true)
on conflict (id) do update set public = excluded.public;

-- Read: anyone may read objects in the images bucket.
drop policy if exists "Public read images" on storage.objects;
create policy "Public read images"
    on storage.objects
    for select
    to anon, authenticated
    using (bucket_id = 'images');

-- Writes: explicitly drop any permissive client write policies that may exist.
-- With none present, anon/authenticated cannot upload/update/delete; only the
-- backend (service role) can write, because it bypasses RLS.
drop policy if exists "Authenticated can upload images" on storage.objects;
drop policy if exists "Authenticated can update images" on storage.objects;
drop policy if exists "Authenticated can delete images" on storage.objects;
drop policy if exists "Anyone can upload images" on storage.objects;
