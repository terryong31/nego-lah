-- Baseline schema for Nego-lah.
--
-- Authoritative reproduction of every table/column the application reads or writes,
-- derived from the backend's actual data access. Uses CREATE TABLE IF NOT EXISTS so
-- it is safe on an existing DB and rebuilds the schema from scratch on a fresh
-- `supabase db push` / `supabase start`.
--
-- Auth lives in Supabase's `auth.users`; ids below that point at a user (buyer_id,
-- user_id, user_profiles.id, chat_settings.user_id) hold that auth uuid but are NOT
-- FK-constrained to the auth schema (kept loose on purpose, like the app).

create extension if not exists "pgcrypto";

-- ============================================================
-- items  (the only table read by clients via the anon key)
-- ============================================================
create table if not exists public.items (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    description text,
    condition   text,
    price       numeric,
    min_price   numeric,                -- minimum acceptable price for AI negotiation
    image_path  text,                   -- JSON string: { "<filename>": "<public_url>" }
    status      text not null default 'available',   -- 'available' | 'sold'
    buyer_id    uuid,                    -- set to the purchasing user when sold
    created_at  timestamptz not null default now()
);

-- ============================================================
-- orders
-- ============================================================
create table if not exists public.orders (
    id                uuid primary key default gen_random_uuid(),
    item_id           uuid references public.items(id) on delete cascade,
    item_name         text,
    buyer_id          uuid,
    amount            numeric,
    status            text not null default 'pending_info',
        -- pending_info | confirmed | shipped | delivered | cancelled | refunded
    stripe_payment_id text,
    recipient_name    text,
    phone             text,
    address           text,
    notes             text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index if not exists orders_buyer_id_idx on public.orders (buyer_id);
create index if not exists orders_item_id_idx on public.orders (item_id);

-- ============================================================
-- transactions  (payment ledger; preserved even if the item is deleted)
-- ============================================================
create table if not exists public.transactions (
    id                uuid primary key default gen_random_uuid(),
    item_id           uuid references public.items(id) on delete set null,
    buyer_email       text,
    amount            numeric,
    stripe_payment_id text,
    status            text not null default 'completed',   -- completed | refunded
    created_at        timestamptz not null default now()
);

-- ============================================================
-- conversations  (AI negotiation history, one row per user)
-- ============================================================
create table if not exists public.conversations (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid,
    item_id    uuid references public.items(id) on delete cascade,
    messages   jsonb not null default '[]'::jsonb,   -- [{role, content, source, timestamp}]
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists conversations_user_id_idx on public.conversations (user_id);

-- ============================================================
-- chat_settings  (per-user AI / admin-intervention flags)
-- ============================================================
create table if not exists public.chat_settings (
    user_id           uuid primary key,
    ai_enabled        boolean not null default true,
    admin_intervening boolean not null default false,
    updated_at        timestamptz not null default now()
);

-- ============================================================
-- user_profiles  (id == auth.users.id)
-- ============================================================
create table if not exists public.user_profiles (
    id           uuid primary key,
    display_name text,
    avatar_url   text,
    is_banned    boolean not null default false,
    updated_at   timestamptz not null default now()
);
