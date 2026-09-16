---
id: SPEC-061
title: Buyer Unread State Survives a Reload
status: complete
priority: high
created: 2026-09-10
tags: [chat, notifications, frontend, supabase]
assigned: agent
---

# Context & Objectives

The buyer's unread badge lives entirely in `useState` and is only ever written
by an SSE `new_message` event. So it exists only for as long as the tab that
saw the message arrive.

Close the tab while the AI is answering (SPEC-060 now makes sure it *does*
answer), come back, and the header dropdown is clean: no chip on the avatar, no
chip on the "Chat" row. The message is sitting in the transcript and nothing on
screen says so. Same for any seller message sent while the buyer was away.

The seller already has a real read watermark (`admin_last_read_at`, SPEC-053).
The buyer needs the mirror of it.

# Acceptance Criteria

- [x] On load, the header chip reflects messages that arrived while the buyer
      was away — no live stream required.
- [x] `unreadCount` is the number of AI/seller messages since the buyer last
      read the conversation, not "since this tab opened".
- [x] Opening `/chat` clears it, server-side, so a second device agrees.
- [x] Returning to a backgrounded tab re-syncs the count.
- [x] A conversation that has never been marked falls back to "messages since
      the buyer's own last message", so existing users don't wake up to their
      entire history marked unread.
- [x] Both endpoints derive the user from the JWT — no `user_id` in the path,
      nothing to scope optionally (`docs/SECURITY_ANTI_PATTERNS.md`).

# Technical Design & Contracts

**Migration** `chat_settings.user_last_read_at timestamptz` (nullable). One
column, mirroring SPEC-053's `admin_last_read_at`. NULL = never marked.

**`GET /chat/unread`** → `{ "count": int, "has_unread": bool }`

    cutoff = max(user_last_read_at, newest human message at)   # either may be NULL
    count  = messages where user_id = me and role = 'ai' and created_at > cutoff

`role = 'ai'` covers both the agent and the seller (the console writes seller
replies as `role='ai', source='admin'`); `system` separators are excluded.
Count is capped at `UNREAD_COUNT_CAP` (99) — a badge, not a ledger.

**`POST /chat/read`** → stamps `user_last_read_at = now()`, returns it.

`GET /chat/history/{user_id}` also stamps: reading the transcript *is* reading
it, and this is the backstop for a hard load that never runs the composable.

**Frontend** `useNotifications`:
- `hydrate()` — `GET /chat/unread`, seeds `hasUnread`/`unreadCount`; skipped
  while the chat page is open and in the foreground.
- called from `connect()` and on `visibilitychange` → visible.
- `clearUnread({ stamp })` — clears locally and fire-and-forgets
  `POST /chat/read` when the clear reflects a real read event: something was
  actually unread, or the buyer is standing on the chat page (where a message
  landing IS being read). `stamp: false` is the sign-out path, which has no
  session to write with. A time-based throttle was considered and dropped: it
  buys nothing at human message rates and would have suppressed exactly the
  writes that keep the watermark honest.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `GET /chat/unread` counts only AI/seller messages newer
      than the watermark; system and human rows are excluded.
- [x] **Scenario 2:** No watermark → counts from the buyer's own last message,
      not from the start of the transcript.
- [x] **Scenario 3:** `POST /chat/read` stamps, and a subsequent unread read
      returns 0.
- [x] **Scenario 4:** Both endpoints reject an unauthenticated caller and only
      ever answer for the token's own user.
- [x] **Scenario 5:** `GET /chat/history` stamps the watermark.
- [x] **Scenario 6 (frontend):** mounting with a pending count shows the chip
      with no SSE event at all. Fails pre-fix.
- [x] **Scenario 7 (frontend):** a message read live on the chat page stamps;
      a `clearUnread()` with nothing to clear, off the chat page, does not; and
      signing out never does.
- [x] **Scenario 8 (frontend):** hydration is skipped while the chat page is
      open and in the foreground, and an unreadable count leaves the header
      working.
- [x] **Scenario 9 (frontend):** a backgrounded tab re-syncs on
      `visibilitychange`.

# Implementation Files

- `supabase/migrations/20260910100000_buyer_conversation_read_state.sql`
- `backend/routes/chat.py` - `GET /chat/unread`, `POST /chat/read`, history stamp
- `frontend/app/composables/useNotifications.ts` - `hydrate()`, stamping `clearUnread()`
- `backend/tests/test_routes_chat_unread.py`, `frontend/tests/composables/useNotifications.test.ts`
