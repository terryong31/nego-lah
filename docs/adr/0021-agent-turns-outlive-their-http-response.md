# ADR 0021: Agent Turns Outlive the HTTP Response That Requested Them

## Status
Accepted

## Context

`POST /chat/stream` ran the entire agent turn inside its `StreamingResponse`
generator. That reads naturally — the turn produces tokens, the generator yields
them — and it was wrong in a way that only shows up when the buyer behaves
normally.

Send a message, close the tab. Starlette notices the disconnect and cancels the
task running the response body. The handler is almost always sitting on
`asyncio.wait_for(turn.__anext__(), …)` at that moment, so the `CancelledError`
lands *inside the agent generator*, mid-token. `agent.bot.chat_stream` never
reaches the `conversation_memory.add_message(user_id, "ai", …)` on its last
line, and the route never reaches `broadcast_to_chat`.

The buyer's own message, however, is written before the first yield. So the
transcript is left holding a question with no answer — and the seller's console
shows an unanswered customer. Nothing logged an error, because nothing had
gone wrong from the code's point of view: a client hung up and the server
cleaned up after it.

The same coupling caused two quieter failures:

- **Nothing was delivered to a buyer who wasn't there.** Delivery (broker
  publish, and the SPEC-052 digest email that seller messages already get) sat
  after the streaming loop, on the path a disconnect skips. The one case that
  needs an out-of-band nudge was the one case that never sent one.
- **The token budget was only enforceable against clients that waited.**
  SPEC-044 B had already patched this with a charge in the generator's cleanup,
  but that could only ever charge for the fragment already streamed, because
  everything after the hang-up was cancelled and never generated.

## Decision

The turn is owned by the conversation, not by the response.

1. **A producer task owns the turn.** `_run_turn` is created with
   `asyncio.create_task` before the response is returned, and holds everything
   with a side effect: the inbound broadcast, the `ai_enabled` check, the token
   budget, the agent stream, the deadline, the charge, and delivery.

2. **A queue is all the response shares with it.** `_TurnRelay` wraps an
   `asyncio.Queue`; `generate()` does nothing but read frames off it and
   `yield _sse(frame)`. A closed tab therefore cancels a relay loop that has no
   application logic to interrupt.

3. **`detach()` bounds the abandoned case.** The response's `finally` marks the
   relay detached, after which `emit()` drops frames instead of queuing them
   behind a reader that is not coming back.

4. **Delivery is unconditional and offline-aware.** `_deliver` broadcasts the
   finished reply and, when `notification_broker.has_subscribers()` is false,
   queues it for the same batched digest a seller message takes.

Running producers are held in a module-level set: `asyncio` keeps only a weak
reference to a task, so without a strong one the garbage collector can stop a
turn mid-sentence — the exact failure this indirection exists to prevent.

## Consequences

**An abandoned turn now costs full inference** instead of being aborted on its
first token. This is the point — the buyer gets the answer they asked for — and
it is bounded three ways that already existed: the 10-messages-per-minute rate
limit, `CHAT_TURN_DEADLINE_SECONDS` (180 s), and the AI token budget, which this
makes *more* enforceable rather than less. Aborting every turn on the first
token, previously an unmetered way to spend the seller's money, now charges for
everything it generates.

**A timed-out turn persists its partial answer, but only when nobody is
watching.** `aclose()` stops the agent before its own `add_message`, so a
partial survives only if the route writes it. A client still on the stream is
offered a retry by the timeout frame, and a persisted partial would then sit in
the transcript in front of the answer that replaces it — so the write is gated
on `relay.attached` being false.

**Server shutdown cancels in-flight turns.** They are ordinary tasks, so a
restart drops whatever was mid-generation. Acceptable: the buyer's message is
already persisted and the next message re-enters a conversation that reads
correctly.

Rejected: keeping the turn in the generator and re-draining it from a detached
task on `GeneratorExit`. The cancellation frequently arrives *while* the
generator is being awaited, so by the time the cleanup runs, the agent has
already been torn down — there is nothing left to hand off.

See `specs/SPEC-060-detached-chat-turn.md`, and
`specs/SPEC-061-buyer-unread-watermark.md` for the buyer-side badge that makes
the delivered reply visible on their next visit.
