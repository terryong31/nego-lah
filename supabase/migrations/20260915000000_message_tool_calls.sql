-- SPEC-087 — what the agent actually did, not just what it said.
--
-- `messages` stores role + content, so a turn that ran `evaluate_offer` is
-- replayed to the model as plain assistant prose. The transcript then
-- demonstrates "buyer names a price -> answer in prose", with no evidence a
-- tool was ever involved, and the self-hosted model follows the demonstration
-- over the system prompt: after two such turns it stops calling the tool and
-- reuses its own last reply with the number swapped, quoting a price that is no
-- longer true.
--
-- Nullable and additive: every existing row keeps replaying exactly as it does
-- today, and the writer degrades to a trace-less insert if this has not been
-- applied yet.
alter table public.messages
    add column if not exists tool_calls jsonb;

comment on column public.messages.tool_calls is
    'SPEC-087. Compact trace of the tool calls this assistant turn made: '
    '[{name, args, id, result}]. Replayed into the agent''s context so the '
    'transcript shows the tool call that produced the answer. NULL for human '
    'turns, admin turns, and any assistant turn that called nothing.';
