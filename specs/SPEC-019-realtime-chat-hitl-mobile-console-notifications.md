---
id: SPEC-019
title: Real-Time Chat, Human-in-the-Loop, Mobile Console, and Notification Gold Standards
status: complete
priority: high
created: 2026-09-05
tags: [realtime, hitl, chat, mobile, stripe, notifications]
assigned: agent
---

# Context & Objectives
This specification addresses 6 interconnected chat, negotiation, and notification UX enhancements:
1. **Real-Time Chat Broken (Item 25):** The Supabase Realtime broadcast payload in `broadcast_to_chat` used incorrect event nesting (`"event": "broadcast"`) instead of `"event": "new_message"`, preventing client listeners from receiving messages. Furthermore, customer messages and AI completion messages in `/chat/stream` were never broadcast to `chat:{user_id}`, causing the admin console to stay blind to live user turns.
2. **Human in the Loop (Item 26):** When the AI agent cannot resolve a query, reaches an impasse, or the user requests human assistance, provide an explicit tool (`transfer_to_human`) that pauses the AI (`ai_enabled=False`, `admin_intervening=True`), injects a system notice, and sends an urgent email alert to the admin with a direct console link. Add an in-console AI toggle in `AdminChats.vue`.
3. **Line Break Bubble Fragmentation (Item 27):** `chat.vue` and `AdminChats.vue` split messages on `\n` into separate bubbles. Messages sent by clients with line breaks must remain in a single chat bubble using `whitespace-pre-wrap`.
4. **Mobile Console Chat Support (Item 28):** `AdminChats.vue` currently relies on `<USplitter>` with horizontal splitting, crushing both conversation list and thread into unusable slivers on mobile. Implement responsive master-detail view switching on mobile (`< md`).
5. **Checkout Link Disabled After Payment (Item 29):** Once an item is paid/sold, checkout action links (`ChatPayCard.vue`) should reflect "Payment Completed" / "Paid" and become disabled to prevent accidental double submissions.
6. **Client-Side Notification for Seller/Agent Messages (Item 30):** Notifications are not received when the AI agent responds or when users are backgrounded/on other pages. Integrate reliable SSE publishing on all message events, robust auth re-connection in `useNotifications.ts`, in-app toasts, and optional Web Notification API support when the tab is backgrounded.

# Acceptance Criteria
- [x] `backend/payment/fulfillment.py` sends valid Supabase Realtime broadcast payloads with `"event": "new_message"` and `ADMIN_SUPABASE_KEY` authentication.
- [x] `backend/routes/chat.py` broadcasts both the incoming human message and the final AI response to `chat:{user_id}`, enabling live bidirectional synchronization with `AdminChats.vue`.
- [x] Added `transfer_to_human` tool to `backend/agent/bot.py`. Calling this tool disables AI in `chat_settings`, injects a system message, broadcasts via Realtime, and dispatches an email alert via `send_human_transfer_alert`.
- [x] `AdminChats.vue` provides an AI status badge and toggle in the thread header to easily resume AI or take over.
- [x] `frontend/app/pages/chat.vue` and `frontend/app/components/admin/AdminChats.vue` preserve newlines in a single bubble with `whitespace-pre-wrap`, extracting only markdown payment links into `ChatPayCard`.
- [x] `frontend/app/components/admin/AdminChats.vue` adapts responsively: master-detail toggle on mobile screens (`< md`) with header back navigation, and dual-pane splitter on desktop (`>= md`).
- [x] `frontend/app/components/chat/PayCard.vue` supports `disabled` and `paid` states, disabling the CTA button and displaying "Payment Completed" when the context item is marked `sold`.
- [x] `backend/routes/chat.py` publishes AI agent replies and system fulfillment notices to `notification_broker`.
- [x] `frontend/app/composables/useNotifications.ts` listens to `onAuthStateChange`, reconnects cleanly, triggers toasts when the user is off `/chat` or `document.hidden`, and integrates the browser Notification API when permitted.
- [x] All automated tests pass across backend and frontend, and `mise run lint` passes with 0 errors.

# Technical Design & Contracts
- **Supabase Realtime Broadcast Payload**:
  ```json
  {
    "messages": [
      {
        "topic": "chat:<user_id>",
        "event": "new_message",
        "payload": {
          "role": "assistant" | "user" | "system",
          "source": "ai" | "human" | "admin" | "system",
          "content": "Message content"
        }
      }
    ]
  }
  ```
- **HITL Tool Definition**:
  ```python
  @tool
  async def transfer_to_human(reason: str, summary: str = "") -> str:
      """Transfers the chat conversation to Terry (the human seller) when the AI cannot help or when requested."""
  ```
- **Admin Email Alert**:
  - `send_human_transfer_alert(user_id, user_email, reason, summary)` sends via Resend to admin with link `https://negolah.my/_console/chats?user={user_id}`.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1 (`test_routes_chat.py`):** Verify `chat_stream` broadcasts incoming customer message and completed AI response to Supabase Realtime and publishes to `notification_broker`.
- [x] **Scenario 2 (`test_agent_bot.py`):** Verify `transfer_to_human` tool updates `chat_settings`, writes system message to `conversation_memory`, and calls `send_human_transfer_alert`.
- [x] **Scenario 3 (`tests/components/chat/PayCard.test.ts`):** Verify `PayCard` renders disabled button with "Payment Completed" when `:paid="true"` or `:disabled="true"`.
- [x] **Scenario 4 (`tests/components/admin/AdminChats.test.ts`):** Verify mobile master-detail layout toggling between list and thread when `selected` is set or cleared.
- [x] **Scenario 5 (`tests/composables/useNotifications.test.ts`):** Verify notification triggers toast when `document.hidden` is true or route is not `/chat`.

# Implementation Files
- `specs/SPEC-019-realtime-chat-hitl-mobile-console-notifications.md` - Specification
- `backend/payment/fulfillment.py` - Broadcast payload correction
- `backend/routes/chat.py` - Stream broadcast + notification publishing
- `backend/agent/bot.py` - `transfer_to_human` tool and escalation logic
- `backend/services/email_service.py` - `send_human_transfer_alert` template
- `frontend/app/components/chat/PayCard.vue` - Disabled/paid state
- `frontend/app/pages/chat.vue` - Non-splitting multiline bubbles + pay card disable
- `frontend/app/components/admin/AdminChats.vue` - Mobile responsive master-detail + multiline bubbles + AI toggle
- `frontend/app/composables/useNotifications.ts` - Robust auth reconnect, background notification detection
- Unit and integration test files for backend and frontend
