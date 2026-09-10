-- SPEC-061 — the buyer gets a read watermark of their own.
--
-- The seller has had one since SPEC-053 (`admin_last_read_at`). The buyer's
-- unread badge, by contrast, lived entirely in a Vue `useState` written only by
-- an SSE `new_message` event — so it existed for exactly as long as the tab
-- that watched the message arrive.
--
-- Close the tab while the agent is answering, come back, and the header
-- dropdown is clean: no chip on the avatar, no chip on the Chat row. The reply
-- is sitting in the transcript and nothing on screen says so.
--
-- One nullable timestamp, mirroring the seller's. NULL means "never marked",
-- and the endpoint then counts from the buyer's own last message instead — so
-- this migration does not wake existing users up to their entire history
-- marked unread.

alter table public.chat_settings
    add column if not exists user_last_read_at timestamptz;

comment on column public.chat_settings.user_last_read_at is
    'When the buyer last read this conversation (opened /chat, or the SPA '
    'stamped it). NULL = never; the unread count then starts from the buyer''s '
    'own newest message.';
