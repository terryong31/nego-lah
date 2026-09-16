---
id: SPEC-087
title: Replay Tool Calls in Agent History
status: complete
priority: high
created: 2026-09-15
tags: [agent, memory, llm, negotiation]
assigned: agent
---

# Context & Objectives

`_build_messages` rebuilds the agent's context from `messages` rows, which store only
`role` and `content`. A turn that ran `evaluate_offer` is replayed as plain assistant prose;
the tool call and its result are gone.

So the transcript the model reads demonstrates: *buyer names a price -> assistant answers in
prose*. There is no evidence in it that a tool was ever involved. Gemini follows the system
prompt anyway. The self-hosted Qwen follows the demonstration, and stops calling the tool
once two of its own price answers are in the window — it reuses its last reply with the
number swapped:

> Buyer: 700? -> "RM700 still too low lah. I can't go lower than RM1150…"
> Buyer: 800? -> "RM800 still too low lah. I can't go lower than RM1150…"
> Buyer: 1000? -> "RM1000 still too low lah. I can't go lower than RM1150…"

RM1000 is this item's floor exactly, so the third answer is wrong: `evaluate_offer` returns
`COUNTER RM1110` for it. The tool was never called.

Measured against the live model, same prompt, same offer, 3 samples each:

| history | tool called |
| --- | --- |
| empty | 3/3 |
| two prior prose answers (what we replay today) | **0/3** |
| the same two turns *including their tool calls* | **3/3** |

A stronger system-prompt rule does not fix it (0/3 with an explicit "your own replies are not
a template" rule), and neither does a prepended synthetic exemplar (0/4) — recent prose wins.
Only restoring the real structure works.

**Objective:** persist the tool calls an agent turn made, and replay them, so the transcript
shows what actually happened.

# Acceptance Criteria

- [x] **Persisted:** `messages.tool_calls` (jsonb, nullable) stores a compact trace —
      `[{name, args, id, result}]` — written for AI turns that called tools.
- [x] **Replayed:** `_build_messages` reconstructs `AIMessage(tool_calls=…)` + one
      `ToolMessage` per call + the assistant's text, in that order.
- [x] **Both turn paths:** `chat()` (from the graph result) and `chat_stream()` (accumulated
      from the stream) both record it.
- [x] **Bounded cost:** traces are replayed only for the most recent `AGENT_TOOL_TRACE_TURNS`
      assistant turns, and each result is truncated — SPEC-059 trimmed this window on purpose.
- [x] **Degrades safely:** if the column does not exist yet, the message is still saved
      without its trace rather than lost.
- [x] **UI untouched:** `get_history_page` does not grow a field the chat client never reads.
- [x] **Cloud unaffected:** the eval still passes 12/12 on Gemini.

# Technical Design & Contracts

```python
# stored shape (one row, jsonb)
[{"name": "evaluate_offer", "args": {...}, "id": "call_x", "result": "COUNTER: …"}]

# agent/memory.py
add_message(..., tool_calls: list[dict] | None = None)
get_history(user_id, limit, include_tool_calls: bool = False)

# agent/bot.py
_replay_ai_turn(messages, row, with_trace: bool) -> None
```

Invariant: an `AIMessage` carrying `tool_calls` is always immediately followed by exactly one
`ToolMessage` per call id — providers reject a dangling call.

# TDD Scenarios

- [x] **S1:** a stored trace is replayed as AIMessage(tool_calls) + ToolMessage + AIMessage.
- [x] **S2:** every replayed tool call has a matching `ToolMessage` id.
- [x] **S3:** a row with no trace replays exactly as before (plain AIMessage).
- [x] **S4:** only the most recent `AGENT_TOOL_TRACE_TURNS` turns carry traces; older ones
      fall back to prose.
- [x] **S5:** `chat()` persists the trace extracted from the graph result.
- [x] **S6:** `chat_stream()` persists the trace accumulated from the stream.
- [x] **S7:** an insert rejected for the unknown column still saves the message.
- [x] **S8:** long tool results are truncated before storage.

# Implementation Files

- `supabase/migrations/20260915000000_message_tool_calls.sql`
- `backend/agent/memory.py`, `backend/agent/config.py`, `backend/agent/bot.py`
- `backend/tests/test_agent_tool_trace_replay.py`
