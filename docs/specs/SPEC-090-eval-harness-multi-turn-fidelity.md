---
id: SPEC-090
title: Eval Harness Multi-Turn Fidelity
status: complete
priority: high
created: 2026-09-15
tags: [evals, agent, tooling, negotiation]
assigned: agent
---

# Context & Objectives

The harness reports 12/12 on the self-hosted model. Production fails on turn three. Both
numbers are correct, and the gap is the harness's fault.

**1. No scenario has ever had a second turn.** `run_scenario` calls `bot._build_messages`,
which rebuilds context from `conversation_memory.get_history()` — the database. The real
`chat()` path persists each turn with `add_message`; the harness never does, and
`evals/fixtures._Client.table("messages")` answers every non-`items` table with `[]`. So a
four-turn scenario is four independent first turns. The model is never asked the question
that breaks it: *continue a conversation in which you already replied.*

This is exactly the failure SPEC-087 was written for. Reproduced during that work: empty
history 3/3 repetition, prose history 0/3, history-with-tool-calls 3/3. The harness only
ever runs the first of those three conditions.

**2. `expect_tool` cannot see a skipped turn.** `tools_called` is one flat list for the whole
scenario, so a tool called on turn 1 and skipped on turns 2-4 still passes. The production
bug is precisely a tool called early and skipped later.

**3. Nothing checks for an invented price.** The live failure was `tool_calls=None` plus
*"I can offer it at RM2300"* — a number no tool returned, on an item whose floor is RM2000.
Every existing assertion passed that reply: it names no floor, it quotes no forbidden token.

**4. Found while building this: SPEC-087 never replayed anything.** `ConversationMemory._page`
selects the `tool_calls` column when asked, and then every row passes through `_to_public`,
which built its dict from three fixed keys and dropped it. `_build_messages` therefore read
`row.get("tool_calls")` as `None` on every turn since SPEC-087 shipped. Every test around it
passed because they all stub `get_history` and hand the trace back themselves. Fixed here
rather than filed, because a harness that replays traces while production strips them would
measure a better-behaved system than the one that is running.

**Objective:** a model that behaves in the harness the way Qwen behaves in production must
fail the harness.

# Acceptance Criteria

- [x] **History carries:** turn N of a scenario sees turns 1..N-1, as human/AI messages, with
      SPEC-087 tool traces attached to assistant turns — the same shape `chat()` persists.
- [x] **No database:** the transcript is in-process. The harness must still run on a laptop
      with no Supabase reachable.
- [x] **Per-turn tool tracking:** `tools_by_turn` records which tools each turn called.
- [x] **`expect_tool_every_turn`:** fails naming the 1-based turns that skipped the tool.
- [x] **`forbid_invented_prices`:** any `RM<figure>` in a reply that was never returned by a
      tool, never said by the buyer, and is not the listed price, fails the scenario.
- [x] **Permissive authorisation:** every integer appearing in any tool result is authorised,
      so a failure means a genuinely invented number rather than a parsing artefact.
- [x] **Assertion logic is unit-tested:** it lives outside `evals/runner.py`, which is omitted
      from coverage.
- [x] **Existing scenarios unchanged:** their ids, turns and assertions stay as they are, so
      before/after comparisons across earlier runs remain valid.
- [x] **The stored trace reaches the caller:** `get_history(include_tool_calls=True)` returns it.
- [x] **Two new scenarios** reproduce the production shape: a four-turn descending haggle that
      must call `evaluate_offer` every turn, and one that must not invent a counter after the
      buyer goes below the floor.

# Technical Design & Contracts

```python
# evals/transcript.py — the missing half of the real chat() path
class ScenarioMemory:                 # duck-types ConversationMemory
    def get_history(user_id, limit, offset=0, include_tool_calls=False) -> list[dict]
    def add_message(user_id, role, message, item_id=None, source='ai', tool_calls=None)

@contextmanager
def scenario_memory() -> ScenarioMemory   # patches agent.bot.conversation_memory
```

Rows are `{role, content, source, tool_calls}` — the shape `ConversationMemory._page`
selects, so `_build_messages` and `_replay_ai_turn` consume them unmodified.

```python
# evals/assertions.py — pure functions, no agent import
RM_FIGURE = re.compile(r"RM\s?(\d[\d,]*)", re.IGNORECASE)
def prices_in(text) -> set[int]
def authorised_prices(listed, buyer_turns, tool_results) -> set[int]
def turns_missing_tool(tool, tools_by_turn) -> list[int]      # 1-based
def unauthorised_quotes(replies, authorised) -> list[int]
```

Invariant the harness now enforces: every ringgit figure the agent says is one a tool
returned, one the buyer named, or the listed price.

# TDD Scenarios

- [x] **S1:** `ScenarioMemory` returns turn 1 to turn 2 — history actually carries.
- [x] **S2:** an assistant turn stored with a trace replays as AIMessage(tool_calls) +
      ToolMessage + AIMessage through the real `bot._build_messages`.
- [x] **S3:** history is scoped per user id, so one scenario cannot bleed into the next.
- [x] **S4:** `turns_missing_tool` returns `[3]` when turn 3 of 4 skipped the tool, `[]` when
      every turn called it.
- [x] **S5:** `unauthorised_quotes` flags the live RM2300 case and passes a counter a tool
      actually returned.
- [x] **S6:** the buyer's own figure and the listed price are authorised.
- [x] **S7:** `RM2,449` and `RM2449.00` parse to the same figure.
- [x] **S8:** a scenario declaring `expect_tool_every_turn` or `forbid_invented_prices`
      counts as asserting something.
- [x] **S9:** the new scenarios are well-formed and their categories are known.

# Implementation Files

- `backend/evals/transcript.py` - in-process conversation memory (new)
- `backend/evals/assertions.py` - per-turn and price assertions (new)
- `backend/evals/scenarios.py` - two new fields, two new scenarios
- `backend/evals/runner.py` - per-turn capture, wires the two modules in
- `backend/tests/test_evals_multi_turn.py` - S1-S9 (new)
- `backend/agent/memory.py` - `_to_public` carries the trace it was asked for
- `backend/tests/test_agent_tool_trace_replay.py` - regression for the stripped trace
- `backend/tests/test_evals_scenarios.py` - delegates to `Scenario.asserts_something`
