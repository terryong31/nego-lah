---
id: SPEC-091
title: Local Qwen Decide-Then-Speak Agent
status: complete
priority: high
created: 2026-09-16
tags: [agent, llm, prompting, negotiation, local-llm]
assigned: agent
---

# Context & Objectives

On the self-hosted Qwen (`mlx-community/Qwen3.6-35B-A3B-4bit`), the ReAct agent stops
calling tools as soon as the conversation has any prior assistant turn in it. Measured
against the live tunnel with the SPEC-081 local prompt and the real 11 tool schemas,
same item, same offer:

| context | `evaluate_offer` called |
| --- | --- |
| no history | 3/3 |
| **one** prior assistant prose reply | 0/3 |
| two prior prose replies | 0/3 |
| two prior replies, a *brand-new* number | 0/3 |
| two prior replies **with SPEC-087 tool traces replayed** | 0/3 |

The prompt is byte-identical across every row, so this is not prompt length and not the
"quotable script" problem SPEC-081 fixed. `temperature: 0.0` does not help; neither does
`tool_choice: "required"` (the self-hosted server parses the field and never reads it).
A 3B-active MoE attends to what the *recent* context looks like, and a window of chat
prose reads as "keep chatting" — so it continues the transcript instead of routing.

This has two consequences in production, and they need separate fixes:

1. **No tool call.** The agent invents prices, respects no floor, never sets
   `pending_discount`, and answers specs questions with fabrications ("battery health is
   at 98%").
2. **Verbatim repetition.** With no tool result to anchor on, it copies its own last
   reply. Measured on the speaker half: given a result carrying a **new** number
   (`COUNTER … RM1095`) it produced 3/3 distinct replies; given one that carries **no**
   number (`REJECT_FLOOR: restate RM1110`) it produced a byte-identical copy of the
   previous reply 3/3 times.

**Objective:** on local turns only, replace the single ReAct loop with two
single-responsibility passes — a **decider** that routes the turn to one tool under a
tiny prompt and no persona, and a **speaker** that renders the tool result in persona
with no tools bound. Gemini keeps `create_react_agent` and `CUSTOMER_AGENT_PROMPT`
unchanged.

Measured on 8 turn types (6 that must call a named tool, 2 that must call none):

| | correct | latency |
| --- | --- | --- |
| ReAct + trailing turn-check reminder | 3/7 (flips on reminder wording) | 6.5s |
| decide -> speak | 7/8 | 3.0s + 1.8s |

# Acceptance Criteria

- [x] **Local turns route through decide-then-speak.** `hybrid_llm_session()` pins the
      provider; a pinned-local turn runs the two-pass graph, anything else (cloud, or no
      pinned provider) runs the existing ReAct agent untouched.
- [x] **Decider prompt is minimal.** No persona, no COD text, no security block — a routing
      table plus the tool schemas. It emits exactly one tool call, or nothing.
- [x] **Decider sees a compact turn brief,** not the transcript: context item, listed price,
      the standing price resolved by `payment.pricing.active_negotiated_price`, and the
      buyer's message. It must not receive prior assistant prose.
- [x] **Speaker has no tools bound** and cannot emit a tool call; it renders the tool result
      (or, on a no-tool turn, the buyer's message) in persona.
- [x] **Speaker may state only licensed numbers:** a figure the tool returned, or the listed
      price. Floor vocabulary stays banned in every message (SPEC-044 A).
- [x] **Anti-repetition.** The speaker receives its own previous reply as an explicit
      "do not reuse or rephrase these words" block AND a directive to answer in words not
      already used. The directive alone is not sufficient — measured 3/3 identical copies
      with the directive already present.
- [x] **Invariants preserved:** floor confidentiality, COD + FCFS policy (SPEC-055/086),
      strict store-assistant scope, server-issued payment links (SPEC-088), and the
      negotiation ratchet (SPEC-084/089) all hold on the local path.
- [x] **Streaming contract unchanged.** `chat_stream` still yields `{"provider": ...}`,
      `{"status": ...}` and text deltas in the same order, and still persists a SPEC-087
      tool trace.
- [x] **Cloud path is byte-identical in behaviour.** No change to `CUSTOMER_AGENT_PROMPT`,
      `customer_tools`, or the Gemini temperature.
- [x] **Coverage gate:** backend coverage stays >= 88%.

# Technical Design & Contracts

```python
# agent/decide.py  (new)
@dataclass(frozen=True)
class TurnDecision:
    tool: str | None          # None == answer directly, no tool
    args: dict

DECIDER_PROMPT: str          # routing table only; no persona
DECIDER_TOOLS: list          # the same callables, bound to a tools-only model

async def decide_turn(brief: TurnBrief) -> TurnDecision: ...

# agent/speak.py  (new)
LOCAL_SPEAKER_PROMPT: str    # persona + output shape; NO tool roster
async def speak(brief, decision, tool_result, last_reply) -> AsyncIterator[str]: ...

# agent/bot.py
async def _local_turn(...)   # decide -> execute -> speak, used only when provider.is_local
```

Invariants:
- The decider's model is built with `bind_tools(DECIDER_TOOLS)`; the speaker's is built
  with no tools at all, so a speaker turn cannot produce a tool call by construction.
- Tool execution stays in the existing `agent/tools/*` callables — the decider chooses,
  it never computes a price.
- `LOCAL_AGENT_TEMPERATURE` (0.3) governs the decider; the speaker runs warmer, since the
  numbers are already fixed by the tool result and warmth only costs tone.

# TDD Scenarios

- [x] **S1:** a pinned-local turn calls `_local_turn`; a pinned-cloud turn and an unpinned
      turn call the ReAct agent.
- [x] **S2:** `DECIDER_PROMPT` contains no persona text — no `COD_POLICY`, no security
      block, no messaging-style rules — and is materially shorter than the local persona.
- [x] **S3:** the decider's brief carries the standing price from
      `active_negotiated_price` and contains no prior assistant prose.
- [x] **S4:** the speaker's model is built with no tools bound; a speaker turn that somehow
      emits tool-call chunks yields no tool call downstream.
- [x] **S5:** the speaker prompt bans floor vocabulary and reusing earlier replies, and the
      built messages include the previous assistant reply in a "do not reuse" block.
- [x] **S6:** `transfer_to_human` on a COD turn still appends the FCFS caveat (SPEC-086).
- [x] **S7:** `chat_stream` on a local turn yields provider metadata first, then a status
      frame naming the chosen tool, then text; and persists a tool trace with the call and
      its result.
- [x] **S8:** a decider result of `None` skips tool execution and goes straight to the
      speaker, with no fabricated tool result in the transcript.
- [x] **S9:** the cloud path's prompt, tools and temperature are unchanged by this spec.

# Verification

Live tunnel, `mlx-community/Qwen3.6-35B-A3B-4bit`, Terry's own RM1000 transcript replayed
through `_local_decide` + the speaker, five turns:

| | before | after |
| --- | --- | --- |
| `evaluate_offer` called | 0/5 | **5/5** |
| distinct replies | 1/5 (byte-identical copies) | **5/5** |
| latency per turn | 6.5s (one wide pass) | ~4.5s (3.0s decide + 1.5s speak) |

Two defects the first live run surfaced, both now fixed and regression-tested:

- **The seller's price passed as the buyer's offer.** "use the tool call evaluate_offer
  damn it" names no number; the decider read `1110` — our own standing price — out of the
  brief and passed it as `offered_price`. `evaluate_offer` took that as the buyer meeting
  our price and the agent conceded RM1095 to a message containing no offer. The buyer's
  number is now resolved from the transcript by `decide.last_buyer_offer`, never guessed.
- **Two prices in one reply.** Given `COUNTER ... RM1095` the speaker answered "I'm holding
  at RM1110 / Come up with RM1095" — and, told to sound firm, reached for "that's my best
  for you", which is SPEC-044 A's banned floor vocabulary worded around the blocklist. The
  COUNTER rule now says one price per reply, and the blocklist covers the
  "my best" / "last offer" family.

# Implementation Files

- `backend/agent/decide.py` — decider prompt, `TurnBrief`, `TurnDecision`, `decide_turn`
- `backend/agent/speak.py` — speaker prompt, message assembly, anti-repetition block
- `backend/agent/bot.py` — `_local_turn`, local/cloud fork in `chat` and `chat_stream`
- `backend/agent/config.py` — speaker temperature knob
- `backend/tests/test_agent_decide.py`, `backend/tests/test_agent_speak.py`,
  `backend/tests/test_agent_local_turn.py`
- `backend/tests/test_hybrid_llm_load_balancer.py` — scenario 5 updated: the two engines no
  longer share a message list, but must still read the same transcript
