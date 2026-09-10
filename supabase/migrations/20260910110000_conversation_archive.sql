-- SPEC-063 — conversations can leave the console list without being destroyed.
--
-- Threads accumulate forever. A conversation that is finished — the deal closed,
-- the tyre-kicker left — has no way out of the list, so the list only grows and
-- "Recent activity" is the only thing keeping it usable.
--
-- Deliberately NOT a delete. `messages` is append-only by design (SPEC-043):
-- a transcript is the record of what was agreed, it is what the seller reads
-- back when a buyer disputes a price, and no triage gesture in a list UI should
-- be able to destroy one. So archiving is one nullable timestamp on the
-- settings row the console already reads in bulk, and unarchiving is clearing
-- it.

alter table public.chat_settings
    add column if not exists archived_at timestamptz;

comment on column public.chat_settings.archived_at is
    'When the seller archived this conversation out of the console list. '
    'NULL = active. Soft state only — no message row is ever removed.';
