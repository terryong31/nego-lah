---
id: SPEC-046
title: Console Chat Operability — AI-Status Sync, Filter, Sort, Search
status: complete
priority: high
created: 2026-09-09
tags: [frontend, backend, admin, chat, hitl]
assigned: agent
---

# Context & Objectives

Two problems with the admin console's Chats view (`AdminChats.vue`):

1. **The AI-status badge goes stale on an auto-handoff (TODO #39).**
   When the agent (`transfer_to_human`) or the rate-limiter hands a conversation
   to the seller, the backend correctly sets `chat_settings.ai_enabled = false` —
   the buyer's AI really is paused. But the console keeps showing **"AI Active"**
   / **"Take over"** because:
   - `GET /admin/chats` never puts `ai_enabled` in its payload, so the
     `watch(selectedChat)` that seeds `currentAiEnabled` always falls to its
     `else` branch (`true`), and the list's "HITL" badge (`v-if="c.ai_enabled === false"`)
     never renders;
   - the only *live* update path is a brittle substring match in the realtime
     `onMessage` handler (`'stepped aside'`, `'joined the chat'`, `'retired from
     the chat and the AI will take over'`) that matches the *manual* toggle's
     notice text but **not** the agent-transfer or rate-limit notices.

2. **The list has no way to work a real queue (TODO #42).**
   Only a read/unread/all filter exists. No sorting, no search. As conversation
   volume grows the seller can't find the one that needs a reply. There is even
   a dead `UDashboardSearchButton` wired to nothing.

# Acceptance Criteria

### #39 — AI-status sync
- [x] `GET /admin/chats` includes `ai_enabled` (default `true`) and
      `admin_intervening` (default `false`) per conversation, read from
      `chat_settings` the same bulk way `GET /admin/users` already does.
- [x] Adding the `chat_settings` / timestamp reads never 500s the endpoint: a
      failed enrichment query degrades to the defaults, conversations still list.
- [x] `AdminChats.vue`: the header badge + Take over / Resume button reflect the
      real `ai_enabled` on chat open (via the existing `watch(selectedChat)`),
      and the list "HITL" badge renders for paused conversations.
- [x] On **any** `system` message arriving over the realtime channel, the
      console re-syncs `currentAiEnabled` from `GET /admin/users/{id}/ai` (the
      authoritative flag) instead of pattern-matching the notice text, and
      `refresh()`es the list. One path covers agent transfer, rate-limit
      handoff, and the manual toggle.
- [x] The old substring matching on system-message text is removed.

### #42 — filter / sort / search
- [x] `GET /admin/chats` includes `last_activity` (ISO timestamp of the most
      recent message in the conversation) so the client can sort by recency.
- [x] Conversation list gains a **sort** control: *Recent activity* (default),
      *Unread first*, *Most messages*. Client-side over the already-loaded list.
- [x] Conversation list gains a **search** input filtering by display name and
      last-message text (case-insensitive, client-side). The dead
      `UDashboardSearchButton` is replaced with a working field.
- [x] Filter (all / unread / read) is unchanged in behaviour; its drifted i18n
      keys are reconciled (`admin.chatsSection.filterAi` / `filterHitl` are
      defined but unused; the component reads `admin.filterUnread` /
      `admin.filterRead`).
- [x] Sort + search + filter compose (applied together) and work on both the
      desktop split-pane and the mobile single-pane layouts.
- [x] New i18n keys added to `en`, `ms`, `zh` (i18n coverage check stays green).

# Technical Design & Contracts

### `routes/admin/chats.py::get_all_chats`
```python
settings = admin_supabase.table('chat_settings').select('user_id, ai_enabled, admin_intervening').execute()
settings_map = {s.get('user_id'): s for s in (settings.data or []) if s.get('user_id')}
# last activity: one narrow query, newest first, first row per user wins
ts_rows = admin_supabase.table('messages').select('user_id, created_at').order('created_at', desc=True).execute()
last_activity = {}
for row in (ts_rows.data or []):
    uid = row.get('user_id')
    if uid and uid not in last_activity:
        last_activity[uid] = row.get('created_at')
```
Each chat dict gains: `ai_enabled` (`setting.get('ai_enabled', True)`),
`admin_intervening` (`setting.get('admin_intervening', False)`),
`last_activity` (`last_activity.get(user_id)`).
Both enrichment reads sit inside the existing `try/except` that already guards
profile enrichment — any failure → defaults, list still returns.

### `AdminChats.vue`
- `ChatSummary` gains `ai_enabled?`, `admin_intervening?`, `last_activity?`.
- `open()` realtime `onMessage`: replace the `if (msg.role === 'system') { if
  (content.includes(...)) ... }` block with
  ```ts
  if (msg.role === 'system') {
    call<{ ai_enabled: boolean }>(`/users/${userId}/ai`)
      .then(r => { currentAiEnabled.value = r.ai_enabled })
      .catch(() => {})
    refresh()
  }
  ```
- `sortKey` ref (`'recent' | 'unread' | 'messages'`), `search` ref.
- `visibleChats` computed = `filteredChats` → search filter → sort. Both list
  templates (desktop `#list`, mobile `aside`) render `visibleChats`; the
  header gains a `USelect` (sort) and a search `UInput`.

# Test-Driven Development (TDD) Scenarios

- [x] **#39-BE-1:** `GET /admin/chats` returns `ai_enabled: false` /
      `admin_intervening: true` for a user with a paused `chat_settings` row, and
      the defaults for a user with no row (`table_router`-based test).
- [x] **#39-BE-2:** `chat_settings` query raising does not fail the endpoint —
      chats still return with `ai_enabled` defaulted to `true`.
- [x] **#39-BE-3:** `last_activity` is the newest message's `created_at` for
      each conversation.
- [x] **#39-FE-1:** a `system` realtime message triggers a `GET /users/{id}/ai`
      and sets the badge from the response (`ai_enabled: false` → "AI Paused"),
      regardless of the notice text.
- [x] **#39-FE-2:** opening a chat whose summary has `ai_enabled: false` shows
      "AI Paused" / "Resume AI" immediately, and the list row shows the HITL badge.
- [x] **#42-FE-1:** typing in the search field narrows the list to rows whose
      name or last message matches (case-insensitive).
- [x] **#42-FE-2:** switching sort to "Most messages" reorders the list by
      `message_count` desc; "Unread first" puts `unread` rows on top; default is
      `last_activity` desc.
- [x] **#42-FE-3:** search + filter + sort compose.
- [x] **#42-FE-4:** i18n — the three locales carry the new keys.

# Implementation Files

- `specs/SPEC-046-console-chat-operability.md` — this spec
- `backend/routes/admin/chats.py` — `ai_enabled` / `admin_intervening` / `last_activity` on `/chats`
- `backend/tests/test_routes_admin_auth.py` — chats-endpoint enrichment scenarios
- `frontend/app/components/admin/AdminChats.vue` — realtime re-sync, sort, search
- `frontend/app/locales/{en,ms,zh}.json` — sort/search keys, reconcile filter keys
- `frontend/tests/components/admin/AdminChats.test.ts` — realtime sync, sort, search
