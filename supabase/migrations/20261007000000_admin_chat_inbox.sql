-- Audit SCL-1 (2026-10-06) — the seller's inbox is one row per conversation,
-- computed by Postgres.
--
-- `GET /admin/chats` used to read every message in `messages`, oldest first,
-- and group them in Python. PostgREST caps a response at `max_rows` (1,000), so
-- once the table passed 1,000 rows the inbox was built from the OLDEST 1,000:
-- buyers who started talking later never appeared, which silently broke the
-- human-handoff path, and ongoing threads froze their last message and count.
--
-- One row per user_id comes back instead — newest message, newest customer
-- message, and the real count — so the response grows with conversations, not
-- with everything ever said. The caller still pages it with `.range()`.
--
-- Read-only and SECURITY INVOKER: it sees exactly what the caller's role sees.
-- `messages` has RLS on and no policies, so only the backend's service role
-- gets rows; the API roles are not even allowed to call it.

create or replace function public.admin_chat_inbox()
returns table (
    user_id        uuid,
    message_count  bigint,
    last_content   text,
    last_role      text,
    last_source    text,
    last_activity  timestamptz,
    last_human_at  timestamptz
)
language sql
stable
security invoker
set search_path = public
as $$
    select distinct on (m.user_id)
        m.user_id,
        count(*) over w,
        left(m.content, 100),
        m.role,
        m.source,
        max(m.created_at) over w,
        max(m.created_at) filter (where m.role = 'human') over w
    from public.messages m
    window w as (partition by m.user_id)
    order by m.user_id, m.id desc;
$$;

revoke all on function public.admin_chat_inbox() from public;
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on function public.admin_chat_inbox() from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on function public.admin_chat_inbox() from authenticated';
    end if;
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        execute 'grant execute on function public.admin_chat_inbox() to service_role';
    end if;
end
$$;
