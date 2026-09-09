---
id: SPEC-053
title: Durable Admin Conversation Read State (Mark as Read)
status: complete
priority: medium
created: 2026-09-09
tags: [admin, console, chat, ux]
assigned: agent
---

# Context & Objectives

The console's unread dot is derived, not stored: `GET /admin/chats` returns
`unread = (last_role == 'human')`. Nothing the operator does can clear it — opening
the conversation, reading it, deciding it needs no answer — because the only thing
that changes `last_role` is *replying*. "Mark as read" does not work because there is
no read state to mark. The Unread filter is therefore a "customer spoke last" filter,
which is a different and less useful question.

Give each conversation a real per-admin read watermark, and let the console set it.

# Acceptance Criteria

- [x] `chat_settings` gains `admin_last_read_at timestamptz` (nullable), applied by a
      migration that is safe to re-run.
- [x] `unread` is true only when the newest **customer** message is newer than
      `admin_last_read_at`. With no watermark the old rule applies, so existing rows
      behave exactly as before the migration.
- [x] A seller reply does not itself mark the thread read — the watermark does, so the
      badge state survives a refresh either way.
- [x] `POST /admin/chats/{user_id}/read` sets the watermark to now and returns the new
      state; `{"read": false}` clears it, marking the thread unread again.
- [x] Sending a message from the console marks that conversation read (you have
      demonstrably seen it).
- [x] Opening a conversation in the console marks it read; the dot clears immediately
      and stays cleared across a list refresh.
- [x] The row carries an explicit Mark read / Mark unread control, so the state is
      reversible without inventing a new message.
- [x] The action is audited like every other console mutation (`chat.read`).

# Technical Design & Contracts

```sql
alter table public.chat_settings
    add column if not exists admin_last_read_at timestamptz;
```

`GET /admin/chats` already bulk-reads `chat_settings` and the newest `messages`
timestamp per user. It additionally records the newest timestamp where
`role = 'human'`, and computes:

```python
unread = last_human_at > admin_last_read_at   if admin_last_read_at else last_role == 'human'
```

Response gains `admin_last_read_at` so the client can render the toggle's direction.

```
POST /admin/chats/{user_id}/read   body: {"read": true}   ->  {"user_id", "unread", "admin_last_read_at"}
```

Frontend `AdminChats.vue`: `open()` fires `markRead(userId)` (optimistic
`c.unread = false`, reconciled by the next refresh); a per-row `i-lucide-mail`/
`i-lucide-mail-open` button toggles it without selecting the row.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1 (no watermark):** a conversation whose last message is `human`
      reports `unread: true` — unchanged legacy behaviour.
- [x] **Scenario 2 (watermark after last customer message):** same conversation with
      `admin_last_read_at` newer than the last human message reports `unread: false`.
- [x] **Scenario 3 (new customer message re-arms):** a human message newer than the
      watermark flips `unread` back to true.
- [x] **Scenario 4 (endpoint writes):** `POST /chats/{id}/read` upserts a timestamp and
      returns `unread: false`; `{"read": false}` writes null and returns `unread: true`.
- [x] **Scenario 5 (audit):** the read endpoint writes an audit row.
- [x] **Scenario 6 (console send marks read):** `POST /chats/{id}/message` stamps the
      watermark.

# Implementation Files

- `supabase/migrations/20260909000000_admin_conversation_read_state.sql` - Column
- `backend/routes/admin/chats.py` - Watermark-aware `unread`, read endpoint
- `backend/schemas.py` - `AdminReadStateRequest`
- `frontend/app/components/admin/AdminChats.vue` - Mark read on open + toggle control
- `frontend/app/locales/{en,ms,zh}.json` - `markRead` / `markUnread` labels
- `backend/tests/test_routes_admin_chats_read_state.py` - Scenarios 1-6
- `frontend/tests/components/admin/AdminChatsReadState.test.ts` - Optimistic clear on open, row toggle
