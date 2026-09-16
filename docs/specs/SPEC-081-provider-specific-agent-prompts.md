---
id: SPEC-081
title: Provider-Specific Agent System Prompts
status: complete
priority: high
created: 2026-09-15
tags: [agent, llm, prompting, negotiation]
assigned: agent
---

# Context & Objectives

One system prompt (`CUSTOMER_AGENT_PROMPT` = `SELLER_PERSONA` + tool roster) is sent to
both engines the hybrid dispatcher routes to (SPEC-020): cloud Gemini and the self-hosted
Qwen. It was written for, and tuned against, Gemini.

On Qwen it fails in a specific and costly way. Asked "what about 2000?", Qwen does not emit
a `<tool_call>` for `evaluate_offer` — it *narrates* one ("Let me check the floor price for
you."), then parrots the persona's own literal example lines back to the buyer ("That's too
low for me. Can you go a bit higher?", "So RM2100? 🛒"). Because `evaluate_offer` never ran:

- no counter-offer number exists (the concession maths lives in the tool, not the model),
- `pending_discount` is never set, so no `data-discount` SSE frame is emitted and the header
  price never moves,
- the agent invents a price that respects no floor.

Two properties of the shared prompt cause it: ~250 lines of persona sit *above* the tool
roster, and the persona quotes, verbatim, the exact buyer-facing sentences that are only
valid *after* a tool result. A weaker instruction-follower copies the nearest matching
string instead of calling the tool.

**Objective:** give each provider its own system prompt, resolved per turn from the provider
already pinned by `hybrid_llm_session()`, so Gemini keeps the prompt it was tuned on and
Qwen gets one written for its failure mode — without forking the persona's security or
policy invariants.

# Acceptance Criteria

- [x] **Per-provider prompt:** `agent/bot.py` exposes `CUSTOMER_AGENT_PROMPT` (cloud, unchanged)
      and `LOCAL_CUSTOMER_AGENT_PROMPT` (self-hosted Qwen).
- [x] **Per-turn resolution:** the compiled graph takes a *callable* prompt so the choice
      follows `llm_factory.current_provider` without recompiling, exactly as
      `_select_customer_model` already does for the model.
- [x] **Cloud is the default:** no pinned provider (scripts, tests, standalone tool calls)
      resolves to the cloud prompt.
- [x] **Tool mandate first:** the local prompt leads with the tool contract, forbids narrating
      tool use in prose, and names `evaluate_offer` as mandatory for any price the buyer states.
- [x] **No quotable scripts:** the local prompt contains no verbatim buyer-facing sentence that
      is only valid after a tool result (no `"Let me check"`, no literal `RM<number>` counter).
- [x] **Rejected numbers and "you go first":** a price the buyer is *rejecting* ("800 also
      cannot") and a request that the seller name a price ("offer me one", "last price?")
      both still require `evaluate_offer`. Measured: these were the two shapes that lost the
      tool call even after the prompt split.
- [x] **Per-provider temperature:** the local turn runs cooler than the cloud turn. Measured
      against the live tunnel on the same prompt and the same bare offer, `evaluate_offer`
      was called 0/3 at 0.7 and 3/3 at 0.3.
- [x] **Invariants preserved:** floor confidentiality, the COD policy, and the strict
      store-assistant scope hold in BOTH prompts.
- [x] **Coverage gate:** backend coverage stays >= 88%.

# Technical Design & Contracts

```python
# agent/config.py
SELLER_PERSONA        # unchanged — cloud / Gemini
LOCAL_SELLER_PERSONA  # new — Qwen; same invariants, directive form, COD_POLICY spliced in

# agent/bot.py
CUSTOMER_AGENT_PROMPT        = SELLER_PERSONA + CLOUD_SYSTEM_INSTRUCTIONS
LOCAL_CUSTOMER_AGENT_PROMPT  = LOCAL_SELLER_PERSONA + LOCAL_SYSTEM_INSTRUCTIONS

def customer_prompt_for(info: ProviderInfo | None) -> str: ...
def customer_temperature_for(info: ProviderInfo | None) -> float: ...
def _select_customer_prompt(state) -> list[BaseMessage]:
    return [SystemMessage(customer_prompt_for(current_provider.get()))] + state["messages"]

create_react_agent(_select_customer_model, customer_tools, prompt=_select_customer_prompt)
```

Invariant: the prompt is chosen from the ContextVar the turn already pinned, so a turn can
never be served by one engine under the other engine's prompt.

# TDD Scenarios

- [x] **S1:** `customer_prompt_for(local_provider_info())` returns the local prompt;
      `cloud_provider_info()` and `None` return the cloud prompt.
- [x] **S2:** `_select_customer_prompt` prepends exactly one `SystemMessage` and preserves
      `state["messages"]` order; inside a pinned-local context it carries the local prompt.
- [x] **S3:** the local prompt mandates `evaluate_offer` and forbids narrating tool use
      (`"let me check"` appears nowhere in it).
- [x] **S4:** the local prompt quotes no literal counter-offer sentence (no `RM2100`-style
      example, no `"So RM"` script).
- [x] **S5:** both prompts carry the floor-confidentiality rule, `COD_POLICY`, and the
      off-topic refusal scope; neither states a numeric floor.
- [x] **S6:** the graph is compiled with a callable prompt, not a frozen string.
- [x] **S7:** the local prompt names both shapes that measurably lost the tool call — a
      rejected number, and the buyer asking the seller to go first — and bans floor
      vocabulary in *any* message, not only on HOLD / REJECT_FLOOR.
- [x] **S8:** `customer_temperature_for` is cooler for local than cloud, defaults to cloud
      when unpinned, and `_select_customer_model` asks for the pinned provider's value.

# Verification

Run against the live tunnel (`mlx-community/Qwen3.6-35B-A3B-4bit`), same item, same prompt:

| Buyer turn | old shared prompt | this spec |
| --- | --- | --- |
| `1000?` | no tool call | `evaluate_offer(1000)` -> `COUNTER RM1110` -> `pending_discount = 1110.0` |
| `bro 800 also cannot, offer me one ...` | no tool call | `evaluate_offer(800)` -> `REJECT_FLOOR` (no counter, by design) |

# Implementation Files

- `backend/agent/config.py` — `LOCAL_SELLER_PERSONA`, `LOCAL_AGENT_TEMPERATURE`
- `backend/agent/bot.py` — `LOCAL_CUSTOMER_AGENT_PROMPT`, `customer_prompt_for`,
  `_select_customer_prompt`, `customer_temperature_for`
- `backend/tests/test_agent_provider_prompts.py`
