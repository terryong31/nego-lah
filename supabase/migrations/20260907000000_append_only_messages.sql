-- SPEC-043 workstream B — conversation history becomes append-only.
--
-- `conversations.messages` is a single jsonb array per user holding that
-- user's entire history. Adding one message meant reading the whole array,
-- appending in Python and writing all of it back, so the cost of saying "ok"
-- grew with everything ever said before it — and because that is a
-- read-then-write, two writers landing together (the AI's reply and an admin
-- typing from the console, say) could each write an array built from the same
-- earlier read, and one message would vanish with no error anywhere.
--
-- One row per message fixes both: a write is an INSERT that touches nothing
-- else, and a read is an indexed page instead of the entire transcript.
--
-- The old column is deliberately left in place and untouched. It is the
-- rollback path, and it stays readable as a frozen snapshot of everything
-- written before the cutover.

create table if not exists public.messages (
    id         bigint generated always as identity primary key,
    user_id    uuid not null,
    -- Unlike conversations.item_id, this does NOT cascade. Deleting a listing
    -- must not delete individual messages out of the middle of a transcript,
    -- which would leave a conversation that reads as if it never happened.
    item_id    uuid references public.items(id) on delete set null,
    role       text not null,
    content    text not null,
    source     text not null default 'ai',
    created_at timestamptz not null default now()
);

-- Every read is "this user's messages, newest first": one page of a
-- negotiation, or the last N for the agent's context window.
create index if not exists messages_user_id_id_idx
    on public.messages (user_id, id desc);

-- Same posture as every other table here: RLS on with no policies at all, so
-- only the backend's service role (which bypasses RLS) can reach it. The
-- browser never reads chat history directly.
alter table public.messages enable row level security;

-- ------------------------------------------------------------
-- Backfill from the jsonb arrays.
-- ------------------------------------------------------------
-- `with ordinality` is what preserves the order the messages were appended in;
-- the array's position is the only record of sequence, since timestamps inside
-- the objects are optional and were written by the app, not the database.
--
-- Guarded so a re-run is a no-op rather than a second copy of every message —
-- this migration has to be safe to apply twice.
with expanded as (
    select
        c.id            as conversation_id,
        c.user_id,
        c.item_id       as conversation_item_id,
        c.created_at    as conversation_created_at,
        m.position,
        m.value,
        -- `timestamp` is optional and was written by the app, so it can be
        -- missing or malformed. Parse defensively: a bad value must not abort
        -- the backfill for everyone else.
        case
            when (m.value->>'timestamp') ~
                 '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'
                then (m.value->>'timestamp')::timestamptz
        end as parsed_at
    from public.conversations c
    cross join lateral jsonb_array_elements(
        case when jsonb_typeof(c.messages) = 'array' then c.messages else '[]'::jsonb end
    ) with ordinality as m(value, position)
    where c.user_id is not null
)
insert into public.messages (user_id, item_id, role, content, source, created_at)
select
    e.user_id,
    -- Prefer the per-message item, falling back to the conversation's own.
    coalesce(
        case
            when e.value->>'item_id' ~ '^[0-9a-fA-F-]{36}$'
                then (e.value->>'item_id')::uuid
        end,
        e.conversation_item_id
    ),
    coalesce(e.value->>'role', 'ai'),
    coalesce(e.value->>'content', ''),
    coalesce(e.value->>'source', 'ai'),
    -- Untimestamped messages inherit the last real timestamp before them
    -- rather than the conversation's start. Falling back to the start would
    -- date a closing "deal" earlier than the offer it accepts — `id` keeps
    -- read order correct either way, but the column would still be telling a
    -- story that never happened, and it outlives this migration.
    coalesce(
        e.parsed_at,
        max(e.parsed_at) over (
            partition by e.conversation_id
            order by e.position
            rows between unbounded preceding and current row
        ),
        e.conversation_created_at
    ) + (e.position * interval '1 millisecond')
from expanded e
where not exists (select 1 from public.messages)
order by e.user_id, e.conversation_created_at, e.position;
