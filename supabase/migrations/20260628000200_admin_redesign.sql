-- Admin module redesign.
--
-- Old model (removed): a standalone `admin_users` table (bcrypt username/password)
-- plus an `admin_allowed_ips` IP allowlist. Replaced by:
--   * Admins = Supabase users with app_metadata.role == "admin".
--   * 2FA login (password + email OTP) handled in the backend.
--   * No IP allowlist.
--   * An audit log of every admin action.

-- ------------------------------------------------------------
-- Drop the retired admin auth tables
-- ------------------------------------------------------------
drop table if exists public.admin_users cascade;
drop table if exists public.admin_allowed_ips cascade;

-- ------------------------------------------------------------
-- admin_audit_log: who did what, when, from where
-- ------------------------------------------------------------
create table if not exists public.admin_audit_log (
    id             uuid primary key default gen_random_uuid(),
    actor_user_id  uuid,
    actor_email    text,
    action         text not null,   -- e.g. login, user.ban, order.delete
    target         text,            -- affected entity id (user_id, order_id, ...)
    ip             text,
    created_at     timestamptz not null default now()
);

create index if not exists admin_audit_log_created_at_idx
    on public.admin_audit_log (created_at desc);

-- Service-role only: RLS on, zero policies. The backend (service role) bypasses
-- RLS to write/read; anon/authenticated clients have no access.
alter table public.admin_audit_log enable row level security;
