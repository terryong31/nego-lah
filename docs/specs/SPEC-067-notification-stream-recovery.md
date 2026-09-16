---
id: SPEC-067
title: The Notification Stream Has To Come Back On Its Own
status: complete
priority: high
created: 2026-09-10
tags: [chat, notifications, frontend, sse]
assigned: agent
---

# Context & Objectives

The buyer sends a message, walks back to the storefront, and the agent's reply
lands two seconds later — with no toast and no chip. Refresh and the chip is
there. A seller's message, from the same broker over the same stream, arrives
fine.

The badge was the wrong place to look. Measured against the live dev stack:
`_deliver` publishes correctly even when the client hangs up mid-turn (proved
against the real ASGI stack over a real socket), and `GET /chat/unread` answers
correctly, which is why a reload always looks right. What the buyer did not have
was a stream: `PUBSUB NUMSUB notify:<uid>` sat at **0** for minutes at a time and
never recovered on its own.

Every failure path in `openStream` ended in a bare `return`:

    catch (err) { console.error('Could not mint a ticket:', err); return }

Nothing scheduled another attempt. One transient failure was therefore
permanent for the life of the page — and in dev, `uvicorn --reload` supplies one
on every backend edit: the stream drops, the retry lands while the server is
still booting, the mint fails, and that tab is never told anything again.

The seller case "works" because it is usually tested seconds after a reload,
inside the window where the stream is still alive.

**What actually killed it.** Everything above is recovery — it assumes something
noticed. Measured against the live stack, the stream was being closed by the
client itself, about four seconds before every send, which is when the buyer
navigates *into* the conversation:

    supabase.auth.onAuthStateChange((_event, session) => {
      if (session?.user) connect()
      else { disconnect(); clearUnread({ stamp: false }) }   // <- any event
    })

Supabase emits plenty of events carrying no session — a refresh in flight, a
re-read on navigation — and every one of them read as "the buyer is gone". The
agent's reply two seconds later then had nowhere to go: no error, no disconnect
to react to, nothing on the client with any reason to reconnect. A seller's
message, arriving while the buyer sat still, found the stream alive. That is the
whole asymmetry.

The same applied to `watch(() => user.value?.id)`, which tore the stream down
whenever that ref read null for a tick.

# Acceptance Criteria

- [x] A failed ticket mint, a failed `EventSource` construction, or a missing
      session schedules another attempt instead of giving up.
- [x] Backoff starts short (most of these are a server coming back up) and is
      capped, so an unreachable API is not hammered.
- [x] A stream that actually opens resets the backoff.
- [x] Signing out stops the retries; nothing reconnects for a user who left.
- [x] A CLOSED-but-non-null `EventSource` no longer blocks reconnection.
- [x] A stream that ends without producing an `error` event is noticed anyway,
      within 15s, by something that looks rather than waits to be told.
- [x] Recovery re-syncs the badge: `openStream` already ends in `hydrate()`, so
      whatever arrived during the outage shows up without a reload.
- [x] HMR does not leak the previous module's stream.
- [x] Only an actual sign-out (`event === 'SIGNED_OUT'`) closes the stream. An
      auth event whose session is momentarily null leaves it alone.
- [x] The user ref reading null never closes the stream; connecting is the only
      thing that watcher does now.
- [x] A retry that comes due after the buyer signed out does not open a stream.

# Technical Design & Contracts

`scheduleReconnect()` — one path for every failure. Guards on an existing timer,
a live stream, and a signed-in user; doubles `RECONNECT_MIN_MS` (1s) up to
`RECONNECT_MAX_MS` (30s); reset to the minimum by the stream's `open` event.

A 15s liveness interval reconnects whenever a signed-in session has no stream
or holds a CLOSED one. Every other path here is driven by an event — `onerror`,
a rejected fetch — and none of them can fire for a connection that goes away
quietly: a frozen tab, a socket closed underneath, an error the browser
swallowed. Measured on the live stack, the server watched subscriptions end
while the client sat there believing it still had one, so the only reliable
detector is one that checks.

`connect()` treats `readyState === CLOSED` as no connection and drops the handle
before reopening. `EventSource` retries its URL by itself, and the ticket in that
URL is single-use (SPEC-056 #6), so its own attempt is guaranteed a 401 — the
composable closes it and comes back with a fresh ticket rather than letting the
browser burn the retry.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** A mint that fails once opens a stream on the retry.
      Fails pre-fix: nothing is ever scheduled.
- [x] **Scenario 2:** A handle left CLOSED without an error event is replaced.
- [x] **Scenario 3:** A stream set to CLOSED with no error event and no
      `close()` call is replaced within 20s by the liveness check alone.
- [x] **Scenario 4:** A `TOKEN_REFRESHED` carrying a null session leaves the
      stream open; a `SIGNED_OUT` closes it. Fails pre-fix — the first one
      closed a healthy stream, which is the bug this whole spec was chasing.
- [x] **Scenario 5:** No retry survives a sign-out, including one already
      scheduled when the buyer left.

**Dev only:** an `import.meta.hot.dispose` hook closes the stream when Vite
replaces the module. The replacement starts with `eventSource = null`, so the
previous copy's stream is orphaned — still connected, still holding one of the
browser's six HTTP/1.1 sockets to the API, with nothing left that can close it.
Caught on the live stack in the ticket log: a ticket minted at 21:59:42 was not
redeemed until 22:00:37, 55s later against a 30s TTL, because the new stream sat
queued behind dead ones until its own ticket expired — which arrives as a 401
and reads exactly like a broken badge.

# Implementation Files

- `frontend/app/composables/useNotifications.ts`
- `frontend/tests/composables/useNotificationsReconnect.test.ts`
