---
id: SPEC-017
title: Chat Notification Fan-out, Self-Notification, and Hand-over Indicator
status: complete
priority: high
created: 2026-09-05
tags: [frontend, backend, chat, notifications, sse, realtime]
assigned: agent
---

# Context & Objectives
Three defects in the buyer's live chat, all visible in one session:

1. **"Cooking…" while the AI is paused.** When the seller takes over (`chat_settings.ai_enabled = false`), `/chat/stream` records the buyer's message and closes the stream with no reply. The client still rendered its AI work indicator, promising an answer that never comes.
2. **The buyer is notified of their own message.** `/chat/stream` calls `broadcast_to_chat(..., source="human")` purely to sync the admin console, but that helper also publishes to the SSE notification broker — so the buyer got a "new message" toast for text they had just typed. System separators ("Terry has joined the chat…") toasted the same way.
3. **The console renders its own message twice.** `send()` appends optimistically, and the backend then broadcasts the same text to `chat:{user_id}` — the channel the console itself is subscribed to — so the echo landed as a second bubble.
4. **Seller messages arrive N times.** Two independent multipliers: `admin_send_message` published to the broker *and* called `broadcast_to_chat` (which publishes too), and `useNotifications()` held its `EventSource` in a per-call closure with no teardown, so every `AppHeader` re-mount (layout changes) leaked another subscribed stream. The broker fans each message to every queue, so five stale streams meant five toasts.

# Acceptance Criteria
- [x] The AI work indicator never renders while `ai_enabled` is false; the seller-typing indicator still does.
- [x] The buyer's chat re-reads `ai_enabled` on load and whenever a system separator arrives, so a mid-conversation hand-over takes effect immediately.
- [x] `broadcast_to_chat` publishes to the notification broker only for messages addressed to the buyer (never `source="human"` or `"system"`); Realtime delivery is unchanged.
- [x] A seller message reaches the buyer's stream exactly once, and renders once in the console that sent it.
- [x] One notification `EventSource` per browser session regardless of how many components call `useNotifications()`, with a single auth listener.

# Technical Design & Contracts
### `backend/payment/fulfillment.py`
`broadcast_to_chat(user_id, content, role, source)` returns before the broker publish when `source in ("human", "system")`.

### `backend/routes/admin.py`
`admin_send_message` keeps `notification_broker.has_subscribers()` for the offline-email fallback but no longer publishes (the `broadcast_to_chat` call above it already did).

### `frontend/app/components/admin/AdminChats.vue`
The realtime `onMessage` handler drops `source === "admin"` payloads, mirroring the customer chat's existing `source === "human"` guard.

### `frontend/app/composables/useNotifications.ts`
`eventSource` / `reconnectTimer` / `connecting` / `authListenerBound` move to module scope. `connect()` is idempotent: it returns early if a stream is open and joins the in-flight promise otherwise.

### `frontend/app/pages/chat.vue`
`aiEnabled` ref fed by `GET /chat/settings/{user_id}`; `aiWorking` is false and `effectiveStatus` is `'ready'` while it is false (unless the seller is typing).

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** `broadcast_to_chat` notifies for `source` `ai`/`admin`, and never for `human`/`system` while still posting both Realtime topics.
- [x] **Scenario 2:** `POST /admin/chats/{id}/message` leaves exactly one event on the subscriber queue.
- [x] **Scenario 3:** A seller send followed by its own broadcast echo leaves exactly one bubble in the console.
- [x] **Scenario 4:** Two mounted consumers of `useNotifications` share one open `EventSource` and produce one toast per event; a disconnect allows a clean re-open.
- [x] **Scenario 5:** With `ai_enabled: false`, `aiWorking` is false and `effectiveStatus` is `ready` mid-"stream"; seller typing still forces `submitted`.
- [x] **Scenario 6:** A system separator on the realtime channel re-reads the setting and flips `aiEnabled`.

# Implementation Files
- `backend/payment/fulfillment.py`, `backend/routes/admin.py` - notification fan-out fixes.
- `backend/tests/test_payment_fulfillment.py`, `backend/tests/test_routes_chat_notifications.py` - regression coverage.
- `frontend/app/composables/useNotifications.ts` - session-scoped stream.
- `frontend/app/pages/chat.vue` - hand-over aware indicator.
- `frontend/app/components/admin/AdminChats.vue` - drops the console's own broadcast echo.
- `frontend/tests/composables/useNotifications.test.ts`, `frontend/tests/pages/chat.test.ts`, `frontend/tests/components/admin/AdminChats.test.ts` - regression coverage.
