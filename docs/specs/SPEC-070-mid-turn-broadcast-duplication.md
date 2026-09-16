---
id: SPEC-070
title: A Broadcast That Lands Mid-Turn Duplicates The Whole Reply
status: complete
priority: high
created: 2026-09-11
tags: [chat, frontend, agent, realtime]
assigned: agent
---

# Context & Objectives

Ask the agent for COD and the answer arrives twice: the same six bubbles above
the handoff separator and again below it. Every other conversation looks fine,
which is why this read as a COD bug — it isn't. COD is simply the only turn that
sends the buyer something *while the reply is still streaming*.

`transfer_to_human` broadcast its separator from inside the tool call, and the
realtime handler pushed it straight into `messages` — the array `useChat` is
streaming into. The SDK only updates a turn that is still the **last** entry:

    const replaceLastMessage = activeResponse.state.message.id === this.lastMessage?.id
    if (replaceLastMessage) this.state.replaceMessage(messages.length - 1, msg)
    else this.state.pushMessage(msg)                        // <- second copy

With a system message on the tail, the next stream write took the `else` branch
and appended the in-flight assistant message again. `replaceMessage`
shallow-copies, so both entries share the live `parts` array — both render the
full reply, identical, on either side of the separator. The push also strands
the typewriter and `typingMessageId`, which follow the tail message.

Two things surfaced while fixing it:

- **A tool cannot hand a value back through a ContextVar.** LangChain runs every
  tool body inside `copy_context()` (`set_config_context`, sync and async), so
  `ContextVar.set()` in a tool writes to a copy the request never reads. This is
  measured, not assumed. `pending_discount` (SPEC-041) is built that way, so its
  `data-discount` frame could never fire in production; its tests pass because
  they set the var from the test's own context.
- **The transcript disagreed with itself.** The tool wrote the separator *before*
  the farewell it explains, while the rate-limit handoff in `_run_turn` writes it
  after. Reload and the divider jumped.

# Acceptance Criteria

- [x] A realtime message arriving while a turn is in flight does not touch
      `messages`; it lands once the turn settles.
- [x] It also waits for the typewriter, since the separator now arrives just
      after the stream closes and the reveal follows the tail message.
- [x] Queued messages flush in arrival order, and the flush replaces the array
      rather than mutating it (`messages` is a `shallowRef`).
- [x] A system separator still re-reads `chat_settings` the moment it arrives.
- [x] The agent's own reply, echoed back on the channel that syncs the seller's
      console, is dropped during the turn and after it.
- [x] A value a tool sets reaches the request that started the turn — through a
      real tool invocation, not a set from the test's own context.
- [x] Two concurrent turns never see each other's signals.
- [x] `transfer_to_human` records the separator; the turn runner writes it after
      the reply, and still writes it when the turn timed out or threw.
- [x] The AI is paused and Terry is emailed inline, not deferred.

# Technical Design & Contracts

**Backend.** `agent/context.py` holds one per-turn `dict` in a ContextVar, opened
by `new_turn()` — called by `_run_turn`, because a box is only isolating if this
task owns it; an inherited one is the same dict two concurrent turns write into.
`pending_discount` and `pending_handoff` are `_TurnSignal` accessors over that
box, ContextVar-shaped so no call site changes. `_flush_handoff_notice` drains
the separator in the turn's `finally`, after `_deliver`.

**Frontend** (`app/pages/chat.vue`): `pendingLive` holds broadcasts that arrive
while a turn is in flight or the typewriter is revealing; the `watch(status)`
that re-reads chat settings flushes it, and so does `stopTyping()`. The AI echo
check also matches the tail message's text, closing the race where the broadcast
lands after the SSE `finish`.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** A system broadcast during `streaming` leaves `messages`
      untouched and the assistant on the tail; it appears after `ready`.
- [x] **Scenario 2:** Two mid-turn broadcasts flush in order, as a new array.
- [x] **Scenario 3:** `/chat/settings` is re-read while the turn is streaming.
- [x] **Scenario 4:** An `ai` broadcast repeating the tail text is dropped with
      the stream already settled.
- [x] **Scenario 5:** A separator arriving after the stream closes waits for the
      reveal to finish. Fails pre-fix: it cuts the reveal short.
- [x] **Scenario 6:** A value set inside a real sync tool and a real async tool
      reaches the request. Fails pre-fix for both — this is the SPEC-041 bug.
- [x] **Scenario 7:** `transfer_to_human` records the notice, leaves
      `ai_enabled=False` and the email alert intact.
- [x] **Scenario 8:** `_run_turn` persists and broadcasts the notice after the
      reply, on the success path and on the error path alike.

# Implementation Files

- `frontend/app/pages/chat.vue`, `frontend/tests/pages/chat.test.ts`
- `backend/agent/context.py`, `backend/agent/bot.py`, `backend/routes/chat.py`
- `backend/tests/test_agent_context.py`, `backend/tests/test_chat_handoff_ordering.py`
- `backend/conftest.py` — `turn_env` moved here, now shared by two specs
- `docs/adr/0024-what-a-tool-hands-back-and-when-the-buyer-sees-it.md`
