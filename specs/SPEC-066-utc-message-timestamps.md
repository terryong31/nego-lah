---
id: SPEC-066
title: Read Watermarks Beat A Server That Isn't On UTC
status: complete
priority: high
created: 2026-09-10
tags: [chat, notifications, backend, bugfix]
assigned: agent
---

# Context & Objectives

The buyer reads the conversation, goes back to the storefront, refreshes — and
the unread chip is back on the avatar. SPEC-061's watermark writes fine and the
count still comes back non-zero.

`ConversationMemory.add_message` stamps every row with
`datetime.now().isoformat()` — **naive local time**. Postgres parses a naive
literal into a `timestamptz` using the session's zone (UTC on Supabase), so a
message written at 18:33 in Kuala Lumpur is stored as `18:33+00`: eight hours
in the future. Every watermark writer, correctly, uses `datetime.now(UTC)`. So
`created_at > user_last_read_at` stays true for the whole UTC offset, and the
chip is unclearable until the wall clock catches up with the row.

This is not only the buyer's chip. SPEC-053's console list compares
`last_human_at > admin_last_read_at` against the same poisoned column, so
"mark as read" in the console doesn't stick either.

Rows already written carry the skew, so fixing the writer alone leaves today's
conversations stuck for up to eight more hours.

There is a second hole behind the same symptom, found while fixing this one:
the buyer's badge is stamped on *arriving* at `/chat`, and the agent's answer
to their own turn is written after that, over the chat page's own stream — which
never touches the notification stream. Nothing moved the watermark past it, so
chatting with the agent and walking away left a chip for a reply the buyer sat
and watched arrive.

# Acceptance Criteria

- [x] `messages.created_at` is written as an aware UTC instant, so it means the
      same thing regardless of where the API process runs.
- [x] Rows already stamped in the future stop counting as unread — on both the
      buyer's chip and the console's dot — without silencing the badge for the
      real messages that follow them.
- [x] A watermark covers the newest message it claims to have read, so two
      clocks a second apart cannot leave a chip that comes back.
- [x] Every other naive `.isoformat()` written into a `timestamptz` column
      (`items.created_at`, `items.deleted_at`, pending-payment `created_at`) is
      aware too — same defect, same one-line fix.
- [x] No data migration: rewriting historical rows would need to guess which
      offset each was written under.

# Technical Design & Contracts

`add_message` → `datetime.now(UTC).isoformat()`. Same for `items.created_at`,
`items.deleted_at`, pending-payment `created_at`.

**The horizon.** Unread state believes nothing dated more than
`MESSAGE_FUTURE_GRACE` (1 minute) ahead of now. `newest_at` and `count_since`
both filter on it, and the console's `_is_unread` applies the same test to the
last customer message. A row past it has not just arrived — it is mis-stamped,
and it is history the reader has already seen. This is what heals the rows
already in the table, with no migration and no guessing at each row's offset.

Crucially it heals them *without* pushing any watermark forward: the obvious
alternative — stamping "read" at the newest row, wherever it is dated — clears
today's chip but then silences the badge for every genuine message until the
wall clock catches up. Eight hours of swallowed notifications is a worse bug
than the one being fixed.

**The anchor.** `read_watermark(user_id, role)` stamps `max(now, newest_at())`
rather than `now`, and both mark-as-read paths use it — `role` being whatever
that side counts as unread ('ai' for the buyer's chip, 'human' for the console's
dot). `now` is this process's opinion; the row was dated by whoever wrote it,
and a mark that stops a second short of the message it claims to cover is a
chip that comes back. Its reach is bounded by the horizon, so it can only ever
move the mark forward by seconds.

**Frontend.** Leaving `/chat`, or backgrounding the tab while on it, stamps —
the arrival stamp only covers what was already there, and the agent's answer to
the buyer's own turn arrives afterwards over the chat page's own stream, which
the badge never sees. Concurrent stamps coalesce into one write, since every
component calling the composable registers its own route watcher.

That watcher lives in a detached `effectScope`, not in the component. `/chat`
has its own layout, so leaving it unmounts the header that owns the watcher and
mounts a new one; Vue disposes a component's pre-flush watchers on unmount and
the layout swap renders first, so a component-scoped watcher never runs for the
one transition it exists for. The stream and the auth listener are at module
scope for the same reason.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `add_message` writes a `created_at` that parses aware and
      lands within a second of `datetime.now(UTC)`. Fails pre-fix — a naive
      literal has no `tzinfo` on any machine, UTC ones included.
- [x] **Scenario 2:** `newest_at` and `count_since` both refuse a row past the
      horizon, so a mis-stamped message is neither the newest thing said nor
      something to badge.
- [x] **Scenario 3:** The console's dot is not re-armed by a future-dated
      customer message.
- [x] **Scenario 4:** `POST /chat/read` stamps over a message dated a few
      seconds ahead of this process's clock, and the console's does the same.
- [x] **Scenario 5:** With nothing newer than now the stamp is still `now`
      (anchoring never drags a watermark backwards), and an unreadable
      `newest_at` still stamps `now` — a chip is not worth a 503.
- [x] **Scenario 6:** `items.create` / soft-delete write aware timestamps.
- [x] **Scenario 7 (frontend):** navigating off `/chat`, and backgrounding the
      tab while on it, each stamp — the buyer's own turn is answered after the
      arrival stamp and over a stream the badge never sees.
- [x] **Scenario 8 (frontend):** two mounted headers produce one write, not
      two: the badge is session state but the composable is per-caller.
- [x] **Scenario 9 (frontend):** the leave stamp survives the header being
      unmounted by the layout swap that the navigation itself causes. Isolated
      in its own file — the main suite leaves every mounted host alive, and
      their watchers answer for the one under test.

# Implementation Files

- `backend/agent/memory.py` — aware `created_at`
- `backend/routes/chat.py` — `_stamp_buyer_read` anchors on the newest AI row
- `backend/routes/admin/chats.py` — `_stamp_read` anchors on the newest human row
- `backend/items.py`, `backend/payment/payment_state.py` — aware timestamps
- `backend/tests/test_agent_memory.py`, `test_routes_chat_unread.py`,
  `test_routes_admin_chats_read_state.py`, `test_items.py`
- `frontend/app/composables/useNotifications.ts` — leaving or backgrounding
  `/chat` stamps too, and concurrent stamps coalesce into one write
- `frontend/tests/composables/useNotifications.test.ts`,
  `useNotificationsRouteScope.test.ts`
- `docs/adr/0022-read-watermarks-anchor-to-the-transcript.md`
