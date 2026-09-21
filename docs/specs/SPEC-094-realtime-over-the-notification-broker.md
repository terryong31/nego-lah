---
id: SPEC-094
title: Realtime Over the Notification Broker, Not a Public Supabase Channel
status: in-progress
priority: high
created: 2026-09-18
tags: [security, negotiation, realtime, frontend]
assigned: agent
---

# Context & Objectives

`core/broadcast.py` publishes message **content** to the Supabase Realtime topic
`chat:{user_id}`. `useTypingChannel` subscribes to that topic with no `private: true`, and no
policy exists on `realtime.messages` — the migrations never enable Realtime Authorization. A
public broadcast topic is readable by any client holding the anon key, which ships in the
JavaScript bundle. Anyone who knows a buyer's user id can therefore stream that buyer's
negotiation in real time: the agent's replies, the buyer's own text, and the system separators
naming the seller.

The app already runs a second, authenticated realtime path for exactly this data —
`notification_broker` in `core/notifications.py`, consumed over SSE at
`/chat/notifications/stream`. Two transports carry overlapping payloads and only one of them
is access-controlled.

**Objective:** one realtime path, authenticated per user. Supabase Realtime leaves the
product, and with it the last reason for supabase-js to be in the bundle (SPEC-093).

# Acceptance Criteria

- [x] **Nothing is published to Supabase Realtime.** `broadcast_to_chat` fans out to the broker
      only; the `POST {SUPABASE_URL}/realtime/v1/api/broadcast` calls are deleted here and in
      `domains/identity/admin_users.py`.
- [x] **Per-user delivery:** a buyer's stream carries only their own conversation. A request for
      another user's stream is rejected, not filtered client-side.
- [ ] **Typing survives both ways:** buyer→seller and seller→buyer typing indicators still work,
      with the same 3s idle expiry and 1.5s send throttle as today. *Unit-tested on both sides;
      not yet watched working between two real browsers.*
- [ ] **Live messages survive:** `new_message` still lands mid-conversation in the buyer's chat
      and in the admin console, including the takeover system separator. *Unit-tested; the
      cross-browser pass is the same manual check as above.*
- [x] **Admin console uses the admin session** for its stream — no anon key, no second protocol.
- [x] **supabase-js is gone** from `frontend/package.json` and the built bundle.
- [x] Backend coverage stays ≥88% (90.12%).

# Technical Design & Contracts

```
POST /chat/typing            {conversation_id, role}   -> 204   (throttled, buyer or admin)
GET  /chat/notifications/stream                        -> SSE   (cookie-authenticated)
GET  /admin/chat/{user_id}/stream                      -> SSE   (admin session)
```

Broker events gain a `kind` discriminator: `typing | new_message | data-discount | read`.
`notification_broker.publish(user_id, …)` is already keyed by user, so authorization is the
session resolving to that same `user_id` — the filtering the public channel never did.

Typing is deliberately fire-and-forget: it is dropped, not queued, when no subscriber is
attached, and it is never persisted.

With SPEC-093 the SSE stream is cookie-authenticated, so `EventSource(url, {withCredentials:
true})` replaces the one-shot ticket minted by `POST /chat/notifications/ticket`; that endpoint
and its Redis key are deleted.

# TDD Scenarios

- [x] **S1:** `broadcast_to_chat` makes no outbound HTTP call; the broker receives the message.
- [x] **S2:** two subscribed users each receive only their own events.
- [x] **S3:** `POST /chat/typing` for a conversation that is not yours -> 403.
- [x] **S4:** a typing event published with no subscriber attached is dropped, not buffered.
- [x] **S5:** the admin takeover separator reaches both the buyer stream and the admin stream.
- [x] **S6 (frontend):** `useTypingChannel` pings over POST and reacts to broker typing events.
- [x] **S7 (frontend):** no module imports `@supabase/supabase-js`.

# Implementation Files

- `backend/core/broadcast.py` — broker-only fan-out
- `backend/core/notifications.py` — `kind` discriminator, typing passthrough
- `backend/domains/negotiation/routes.py` — `POST /chat/typing`, stream auth, ticket removal
- `backend/domains/negotiation/admin_routes.py` — admin SSE stream
- `backend/domains/identity/admin_users.py` — drop the direct broadcast call
- `frontend/app/composables/useTypingChannel.ts` — broker transport
- `frontend/app/composables/useNotifications.ts` — `withCredentials`, no ticket
- `frontend/app/components/admin/AdminChats.vue`
- `frontend/nuxt.config.ts`, `frontend/package.json` — supabase-js removed
