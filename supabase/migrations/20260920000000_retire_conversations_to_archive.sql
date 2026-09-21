-- SPEC-098 — retire `public.conversations` without destroying it.
--
-- This is the pre-SPEC-043 chat history: one row per user, the whole transcript
-- in a jsonb array. SPEC-043 replaced it with `public.messages` (one row per
-- message) and deliberately left this table as the rollback path. Nothing has
-- read it since, and SPEC-097 gave it an owner rather than dropping it.
--
-- It is MOVED, not dropped. Supabase exposes only the `public` schema over
-- PostgREST, so relocating the table takes it off the API surface while every
-- row, index, constraint and grant travels with it untouched.
--
--   TO REVERSE THIS MIGRATION, one statement:
--       alter table archive.conversations set schema public;
--
-- The actual DROP is a separate migration for a later day, once the archived
-- table has sat untouched long enough to be boring. This file exists to make
-- deferring that decision cheap rather than to pre-empt it.

create schema if not exists archive;

comment on schema archive is
    'Retired tables kept for rollback and forensics. Not exposed over PostgREST '
    '(Supabase serves `public` only) and not read by the application.';

do $$
declare
    v_users_with_history bigint;
    v_new_rows           bigint;
    v_shortfall          bigint;
begin
    -- Idempotent: re-applying this file must be a no-op, not an error.
    if not exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'conversations'
    ) then
        raise notice 'SPEC-098: public.conversations is already retired; nothing to do.';
        return;
    end if;

    ----------------------------------------------------------------------
    -- Guard 1 — did the backfill ever run?
    --
    -- SPEC-043's backfill is guarded by `where not exists (select 1 from
    -- public.messages)`. A single pre-existing row in `messages` would have
    -- skipped the whole thing, leaving this table as the ONLY copy. That is
    -- the one state where archiving would quietly strand real history.
    ----------------------------------------------------------------------
    select count(*) into v_users_with_history
      from public.conversations
     where user_id is not null
       and jsonb_typeof(messages) = 'array'
       and jsonb_array_length(messages) > 0;

    select count(*) into v_new_rows from public.messages;

    if v_users_with_history > 0 and v_new_rows = 0 then
        raise exception
            'SPEC-098 refusing to retire public.conversations: % user(s) hold history there and '
            'public.messages is empty. The SPEC-043 backfill was skipped by its own guard, so this '
            'table is the only copy. Re-run the backfill before archiving.',
            v_users_with_history;
    end if;

    ----------------------------------------------------------------------
    -- Guard 2 — is anyone's transcript shorter now than the snapshot?
    --
    -- Compared per USER, summed across their rows: a user may hold several
    -- conversations rows (one per item), and comparing row-by-row would miss
    -- a shortfall that only shows in the total.
    --
    -- Restricted to accounts that still exist. `purge_user_data` deletes a
    -- user's `messages` and `chat_settings` and has never touched this table,
    -- so old history with no new history is the CORRECT end state of a deleted
    -- account — counting it here would block the migration on healthy data.
    -- Item deletes cascade rows out of this table too, which can only ever make
    -- the old side smaller, never the new side.
    ----------------------------------------------------------------------
    select count(*) into v_shortfall
      from (
            select c.user_id,
                   sum(
                       case when jsonb_typeof(c.messages) = 'array'
                            then jsonb_array_length(c.messages) else 0 end
                   ) as old_count,
                   (select count(*) from public.messages m where m.user_id = c.user_id) as new_count
              from public.conversations c
             where c.user_id is not null
               and exists (select 1 from public.user_profiles p where p.id = c.user_id)
             group by c.user_id
           ) t
     where t.old_count > 0
       and t.new_count < t.old_count;

    if v_shortfall > 0 then
        raise exception
            'SPEC-098 refusing to retire public.conversations: % live account(s) have fewer rows in '
            'public.messages than their old array holds. Run '
            '`mise run db:verify:conversations:prod` to see which, and why.',
            v_shortfall;
    end if;

    ----------------------------------------------------------------------
    -- Both guards clear. Move it.
    ----------------------------------------------------------------------
    execute 'alter table public.conversations set schema archive';
    raise notice 'SPEC-098: moved public.conversations -> archive.conversations (% users, % messages archived).',
        v_users_with_history, v_new_rows;
end $$;

-- Belt and braces. The table kept RLS enabled with no policies, so only the
-- service role could ever read it, and PostgREST no longer serves the schema
-- at all — but the API roles' grants travelled with the table, so take them
-- away explicitly. Guarded because these roles exist on Supabase, not on a
-- bare Postgres someone points `run_migrations.py` at.
do $$
begin
    if not exists (
        select 1 from information_schema.tables
        where table_schema = 'archive' and table_name = 'conversations'
    ) then
        return;
    end if;

    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on archive.conversations from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on archive.conversations from authenticated';
    end if;

    execute $c$
        comment on table archive.conversations is
            'Retired 2026-09-20 by SPEC-098. Pre-SPEC-043 chat history, superseded by '
            'public.messages. Read by nothing. Restore with: '
            'alter table archive.conversations set schema public;'
    $c$;
end $$;
