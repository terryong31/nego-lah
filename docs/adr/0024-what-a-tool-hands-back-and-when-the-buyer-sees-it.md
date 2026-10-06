# ADR-0024: What a Tool Hands Back, and When the Buyer Sees It

- Status: Accepted
- Date: 2026-09-16

## Context

Ask the agent for cash on delivery and the reply arrived twice — the same six
bubbles above the handoff separator and again below it. Every other
conversation looked fine, so it read as a COD bug. It wasn't. COD is simply the
only turn that sends the buyer something *while the reply is still streaming*.

Three separate mechanisms met in that one turn.

**1. The client's message list has one writer at a time.** `useChat` streams
into `messages`, and it can only update a turn that is still the last entry:

```js
const replaceLastMessage = activeResponse.state.message.id === this.lastMessage?.id
if (replaceLastMessage) this.state.replaceMessage(messages.length - 1, msg)
else this.state.pushMessage(msg)        // a second copy of the same reply
```

The realtime handler pushed the separator straight onto that array. With a
system message on the tail, the stream's next write took the `else` branch and
appended the in-flight assistant message a second time. `replaceMessage`
shallow-copies, so both entries shared the live `parts` array and both filled in
with the whole reply. The same push also stranded the typewriter, which reveals
the tail message and nothing else.

**2. A ContextVar cannot carry a value out of a tool.** The obvious fix — let
the tool record the separator and have the request write it after the reply —
does not work the obvious way. LangChain runs every tool body inside
`copy_context()` (`set_config_context`, sync and async paths alike), so a
`ContextVar.set()` inside a tool writes to a copy the request never reads.
Measured, not assumed: a probe var set in a tool reads back as `None` the moment
the tool returns.

That is not a hypothetical. `pending_discount` (SPEC-041) was built exactly that
way, and its `data-discount` frame could never fire in production — the live
price on the chat header only ever moved on a refetch. Its tests passed because
they set the variable from the test's own context, which is the one place the
broken version looks like it works.

**3. The transcript disagreed with itself.** `transfer_to_human` persisted the
separator before the farewell it explains, while the rate-limit handoff on the
next code path down persisted it after. Reload and the divider jumped.

## Decision

**A turn hands values back through one box, not through variables.** A single
ContextVar holds a per-turn `dict`, opened by the request (`new_turn()`) before
the agent runs. The tools' copied contexts all hold a reference to that same
dict, so what they write into it is visible to the request. `pending_discount`
and `pending_handoff` are `_TurnSignal` accessors over that box — ContextVar
shaped (`get`/`set`), because that is all the call sites ever wanted.

Isolation is unchanged and now stronger: the box is opened by `_run_turn`, in
the request's own task, rather than inherited from whatever context happened to
be around. An inherited box is the *same dict* two concurrent turns would both
write into — the route is the only layer that can guarantee it isn't.

**The separator goes out after the reply.** The tool still flips
`chat_settings.ai_enabled` and emails Terry inline — those are the decision, and
a message arriving in the meantime must not be answered by an agent that has
stepped out. Only the separator is deferred, drained in the turn's `finally` so
a turn that timed out or threw still tells the buyer why nobody is answering.

**Nothing outside the SDK touches `messages` while a turn is in flight.**
Broadcasts arriving mid-turn queue in `pendingLive` and land when the turn
settles — and, since the separator now arrives just after the stream closes,
they wait for the typewriter's reveal too. The flush replaces the array rather
than mutating it: `messages` is a `shallowRef`, so an in-place push after the
SDK stops writing renders nothing.

## Consequences

- The live price chip works for the first time (SPEC-041's frame now reaches the
  client), which is a behaviour change nobody asked for in this fix and should
  be watched on the next negotiation.
- A tool that wants to reach the request must go through a `_TurnSignal`. A bare
  `ContextVar.set()` inside a tool is silently discarded — the tests for this
  live in `test_agent_context.py` and exercise a real tool invocation, not a
  set from the test's own context.
- Anything the seller sends during an agent turn is now shown a beat later,
  after the reveal, rather than jumping in mid-sentence.
- The transcript reads the same live and on reload: reply, then separator.

## Related

- SPEC-070 — the spec this came from
- ADR 0021 — the turn already outlives its response; this decides what it leaves
  behind on the way out
