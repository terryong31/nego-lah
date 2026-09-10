---
id: SPEC-063
title: Conversation Row Actions Menu (Archive / Read / Info)
status: complete
priority: medium
created: 2026-09-10
tags: [admin, frontend, nuxt-ui, supabase]
assigned: agent
---

# Context & Objectives

Every conversation row ends in a single mail icon that toggles read state. It is
the only per-row action the console has, it costs a whole affordance to do one
thing, and its two icons (`mail` / `mail-open`) read as "send mail" rather than
"mark read" — the screenshot that prompted this spec has both rows showing an
envelope with no indication of what it does.

An operator working a list needs more than one verb per row: triage it, get it
out of the way, or find out who they are talking to. That is a menu, not a
button.

Threads also accumulate forever. A conversation that is finished — the deal
closed, the tyre-kicker left — has no way to leave the list, so the list only
ever grows and "Recent activity" is the only thing keeping it usable.

# Acceptance Criteria

- [x] Each row's trailing control is an `i-lucide-ellipsis-vertical`
      `UDropdownMenu`, not the mail toggle.
- [x] The menu offers **Mark as read / Mark as unread** (existing behaviour,
      same optimistic write and rollback), **Archive / Unarchive**, and
      **User Info**.
- [x] Archiving is reversible and destroys nothing: message rows are untouched.
- [x] Archived conversations leave the default list and are reachable through
      an archive toggle in the control strip.
- [x] Archive and unarchive are audited (`chat.archive` / `chat.unarchive`) and
      go through the console's existing admin + CSRF gate.
- [x] The unread `UChip` stays on the row; it is state, not an action.
- [x] User Info opens a `USlideover` showing display name, avatar, email, user
      id (in the panel's own type, not a mono face — it is a value like any
      other), joined date, banned state, message count, and last activity. It is
      titled for what it is ("User Info"), not for whoever it happens to be
      showing — the display name is already the first line of its body. AI
      status is deliberately absent: the thread header shows it beside the
      control that changes it.
- [x] Mobile rows get the same menu.

# Technical Design & Contracts

**Migration** `chat_settings.archived_at timestamptz` (nullable). NULL = active.
Soft state on the settings row the console already reads in bulk — no new
table, no writes to `messages`.

**`POST {ADMIN}/chats/{user_id}/archive`** body `{ "archived": bool }` →
`{ user_id, archived, archived_at }`. Mounted on the `protected` router, so
`verify_admin` + `verify_csrf_token` apply automatically. Stamps
`archived_at = now()` or NULL, then `write_audit(...)`. A failed write raises
503 rather than resolving to a silent no-op (SPEC-053's rule).

**`GET {ADMIN}/chats`** gains `?include_archived=false` (default) and returns
`archived: bool` plus `email`, `created_at`, `is_banned` per row — the handler
already holds `users_map`/`profiles_map`, so the customer-info panel costs no
extra round trip and no new endpoint.

**Frontend** `AdminChats.vue`:
- `rowActions(chat)` builds `DropdownMenuItem[][]`: read toggle, archive
  toggle, separator, customer info.
- `showArchived` ref drives an `i-lucide-archive` toggle in the control strip
  (left of refresh) and the `include_archived` query param.
- `infoChat` ref drives a `USlideover` rendered once, outside the row loop.

The thread header is sized `md` throughout to match the list's control strip
across the splitter (SPEC-062). It previously mixed a `2xs` avatar, an `md`
badge and an `xs` button: they lined up on paper and read as three unrelated
rows of controls. The mobile thread header keeps its compact sizing — it shares
a 375px row with a back button.

The AI status badge is gone from both headers. The toggle beside it already
carried the same fact, and carried it as an action: "Take over" can only be
offered while the agent is answering, "Resume AI" only while it is not. Tests
that asserted the badge text now assert the button label, which is the thing an
operator actually reads and clicks.

`useAsyncData` also gains `deep: true`. Nuxt 4 hands `data` back as a shallow
ref, so mutating a row in place — what every optimistic action here does —
changes nothing a computed is watching. `markRead` only ever *appeared* to work
because the `markingRead` ref re-rendered the child around it; a row leaving the
list on archive is decided by a computed and had no such accident to lean on.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `POST /chats/{id}/archive` with `archived: true` stamps
      `archived_at` and writes an audit row; `false` clears it.
- [x] **Scenario 2:** A failed stamp returns 503, not 200.
- [x] **Scenario 3:** The endpoint is unreachable without an admin session and
      without a CSRF token.
- [x] **Scenario 4:** `GET /chats` omits archived conversations by default and
      includes them (flagged `archived: true`) with `include_archived=true`.
- [x] **Scenario 5:** `GET /chats` rows carry `email`, `created_at`,
      `is_banned`.
- [x] **Scenario 6 (frontend):** the row renders an ellipsis trigger and no
      mail button.
- [x] **Scenario 7 (frontend):** the menu's archive item calls the endpoint and
      drops the row from the default list optimistically, restoring it on
      failure.
- [x] **Scenario 8 (frontend):** User Info opens the slideover with the row's
      identity fields, titled "User Info" with no subtitle, and carrying no AI
      badge.

# Implementation Files

- `supabase/migrations/20260910110000_conversation_archive.sql`
- `backend/routes/admin/chats.py`, `backend/schemas.py` (`AdminArchiveRequest`)
- `frontend/app/components/admin/AdminChats.vue`, `AdminChatList.vue`
- `frontend/app/locales/{en,ms,zh}.json`
- `backend/tests/test_routes_admin_chats_archive.py`
- `frontend/tests/components/admin/AdminChatsRowActions.test.ts`
