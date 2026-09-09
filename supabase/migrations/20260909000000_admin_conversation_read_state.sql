-- SPEC-053 — the console gets a real read watermark.
--
-- `GET /admin/chats` derived `unread` from "did the customer send the last
-- message?". That is a useful signal but it is not read state: the only act
-- that can clear it is replying, so an operator who reads a thread and decides
-- it needs no answer is stuck looking at a dot forever, and "mark as read" had
-- nothing to write to.
--
-- One nullable timestamp per conversation is the whole feature. NULL means
-- "never marked", and the endpoint keeps answering with the old rule for those
-- rows, so this migration changes nothing until someone clicks something.
--
-- Single-seller store: one watermark per conversation, not per admin. When
-- there is more than one operator this becomes a join table keyed
-- (user_id, admin_id) — deliberately not built for a seller count of one.

alter table public.chat_settings
    add column if not exists admin_last_read_at timestamptz;

comment on column public.chat_settings.admin_last_read_at is
    'When the seller last marked this conversation read in the admin console. '
    'NULL = never marked; the console then falls back to "customer spoke last".';
