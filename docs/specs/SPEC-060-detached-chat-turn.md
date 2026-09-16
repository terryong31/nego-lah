---
id: SPEC-060
title: Agent Turn Survives the Buyer Closing the Tab
status: complete
priority: high
created: 2026-09-10
tags: [chat, agent, reliability, notifications]
assigned: agent
---

# Context & Objectives

Send a message, close the tab, come back: no reply. Ever.

`POST /chat/stream` runs the whole agent turn *inside* the `StreamingResponse`
generator. When the browser hangs up, Starlette cancels that task, so:

1. `CancelledError` lands at whichever `await` the handler is sitting on —
   usually `asyncio.wait_for(turn.__anext__(), …)`, which cancels the agent
   generator mid-token;
2. `agent.bot.chat_stream` never reaches its trailing
   `conversation_memory.add_message(user_id, "ai", …)`, so the reply is never
   persisted;
3. the route never reaches `broadcast_to_chat`, so the SSE broker and the
   SPEC-052 digest never hear about it either.

The buyer's own message *is* saved (it is written before the first yield), so
the transcript reads as a question the seller ignored.

The turn must not be owned by the HTTP response. It is owned by the buyer's
conversation; the response is one optional viewer of it.

# Acceptance Criteria

- [x] A turn whose client disconnects mid-stream runs to completion: the reply
      is persisted, broadcast, and delivered on the buyer's next visit.
- [x] Disconnecting never cancels the agent generator; `hybrid_llm_session`'s
      lease is released by the turn finishing, not by the hang-up.
- [x] The AI token budget is charged exactly once per turn, on every exit path
      (completed, timed out, errored, abandoned) — SPEC-044 B still holds.
- [x] `CHAT_TURN_DEADLINE_SECONDS` still bounds a detached turn, so an
      abandoned turn cannot run forever.
- [x] An AI reply that lands while the buyer has no live SSE stream is queued
      for the SPEC-052 batched digest, exactly as a seller message is.
- [x] Frames produced after the client is gone are dropped, not buffered
      without bound.
- [x] A turn that times out with the client already gone persists its partial
      answer rather than dropping it — `aclose()` stops the agent before its own
      `add_message`, and there is nobody left to take the retry the timeout
      frame offers.

# Technical Design & Contracts

`routes/chat.py` splits the handler in two.

**Producer** — `_run_turn(...)`, an `asyncio.Task` created before the response
is returned. It owns everything the old `generate()` body did: the incoming
broadcast, the `ai_enabled` check, the token-budget branch, the agent stream,
the deadline, the charge, the outgoing broadcast, and the new digest queue. It
emits AI-SDK UI-message frames (plain dicts) into a `_TurnRelay`.

**Relay** — `_TurnRelay` wraps an `asyncio.Queue`. `emit()` is a no-op once
`detach()` has been called, so an abandoned turn stops accumulating frames.

**Response** — `generate()` only relays: `async for frame in relay.frames()`,
`yield _sse(frame)`, then `data: [DONE]`. Its `finally` calls `relay.detach()`
and nothing else. Cancellation therefore reaches no application logic.

Running tasks are held in a module-level set (`asyncio` keeps only a weak
reference to a task; without a strong one the GC can stop a turn mid-sentence).

No HTTP contract changes: same URL, same frame types, same ordering.

**Trade-off (accepted):** an abandoned turn now costs full inference instead of
being aborted on the first token. That is the point — the buyer gets their
answer — and it is bounded by the existing 10/min message rate limit, the
180 s turn deadline, and the AI token budget, which this makes *more*
enforceable, not less.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** Drive the endpoint's generator, read one token, `aclose()`
      it. The agent's remaining chunks are still consumed, the reply is
      persisted via `conversation_memory.add_message(role="ai")` with the FULL
      text, and `broadcast_to_chat` is called once. Fails pre-fix.
- [x] **Scenario 2:** Same hang-up, with `notification_broker.has_subscribers`
      false — `queue_unread_message` receives the full reply.
- [x] **Scenario 3:** Same hang-up, subscriber present — nothing is queued.
- [x] **Scenario 4:** An abandoned turn is charged exactly once, after it
      finishes, and the charge covers the tokens generated post-hang-up.
- [x] **Scenario 5:** Completed / timed-out / errored turns keep their existing
      single-charge behaviour and frame sequences (existing suite, unchanged).
- [x] **Scenario 6:** A detached turn that exceeds the deadline still ends,
      charges, and delivers whatever it produced.
- [x] **Scenario 7:** Hanging up does not cancel the agent generator — its body
      runs to completion, which is what releases the LLM lease.

# Implementation Files

- `backend/routes/chat.py` - `_TurnRelay`, `_run_turn`, relay-only `generate()`
- `backend/tests/test_chat_detached_turn.py` - new coverage
- `backend/tests/test_chat_budget_accounting.py` - abandonment test restated
  against the new contract (the turn completes, then charges)
- `docs/adr/0021-agent-turns-outlive-their-http-response.md` - the decision
