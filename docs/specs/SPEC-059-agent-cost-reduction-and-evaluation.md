---
id: SPEC-059
title: Agent Cost Reduction - Item Knowledge Card over Per-Turn Vision, and a Harness to Prove It
status: complete
priority: high
created: 2026-09-10
tags: [agent, cost, llm, evaluation]
assigned: agent
---

# Context & Objectives

Every negotiation turn re-sends the item's photos to the model.
`agent/bot._build_messages` attaches up to two `image_url` parts whenever an
`item_id` is in context — on turn 1 and identically on turn 20. Gemini bills each
image at roughly 258+ tokens and pays vision prefill latency for it, so a 20-turn
haggle over one item pays for ~40 image ingests to learn nothing it did not know
after the first.

The redundancy is worse than it looks: `items.description` was *itself* generated
from those same photos by `image_analyzer.analyze()` at listing time. The model is
being handed a picture and a description of the picture, every turn, forever.

**The fix is to send what we already know instead of what we already showed.** A
compact text knowledge card, assembled from the listing row, replaces the images
on the ordinary turn; images are attached only when the buyer actually asks
something the card cannot answer, or uploads a photo of their own.

TODO 45 also asks for this to be *measured* rather than asserted, hence the eval
harness — which is also how "should we switch to a cheaper model?" (TODO 52) gets
an answer instead of a guess.

# Acceptance Criteria

- [x] **Knowledge card.** `agent/knowledge.py` renders name, price, condition and a
      trimmed description into a compact block. Missing fields are omitted, never
      rendered as "None".
- [x] **Images are the exception, not the default.** `_build_messages` attaches item
      images only when the turn needs vision: the buyer uploaded a file, or their
      message asks something visual (scratch/colour/photo/condition…). Otherwise
      the card goes in alone.
- [x] **Buyer uploads always reach the model.** Cost control must never silently
      drop a photo the buyer sent.
- [x] **History window is bounded and tunable.** `AGENT_HISTORY_TURNS` (default 20,
      was a hard-coded 50) caps the replayed transcript.
- [ ] **~~Item lookups are cached.~~** *Dropped deliberately.* The per-turn lookup is
      one indexed read — latency, not tokens, and tokens are what this spec is
      about. A second cache would need a second invalidation path alongside
      `invalidate_item_cache`'s six call sites, and the failure mode of missing
      one is the agent quoting a **stale price** to a buyer. Not a trade worth
      making days before launch for a saving the cost report cannot even see.
- [x] **Cost is computable.** `agent/cost.py` holds a per-model price table and
      turns real `usage_metadata` into RM. Unknown models return None rather than
      inventing a number.
- [x] **Eval harness.** `evals/` replays scored negotiation scenarios, records real
      token usage, latency and cost per scenario, and prints pass rate per
      category beside cost. `mise run eval:agent`. Deliberately outside pytest —
      it calls a real model.
- [ ] **~~Ragas.~~** *Attempted, then rejected — see the comment above
      `evals.runner._judge_relevancy`.* Every release through 0.4.3 hard-imports
      `langchain_community.chat_models.vertexai`, removed in langchain-community
      0.4.x, so `import ragas` raises before any metric is reachable. Adding it
      to the lockfile at all dragged **production** packages backwards (`rich`
      15.0.0 → 14.3.4, `openai` 3.7.0 → 3.3.0) because uv resolves one version
      per package across every group. Replaced by a few-line LLM judge using a
      dependency the repo already has; `_judge_relevancy` is the seam to swap
      back if ragas ever drops that import.
- [x] **Model comparison.** `--model` runs the same suite against another model so
      the flash-lite question is answered with numbers.
- [x] **No behavioural regression.** The negotiation floor, HITL and checkout paths
      are untouched; the existing suite stays green.

# Technical Design & Contracts

```python
# agent/knowledge.py
item_knowledge_card(item: dict) -> str      # text block for the system context
turn_needs_vision(message: str, files, has_description: bool) -> bool

# agent/cost.py
MODEL_PRICING: dict[str, ModelPrice]        # USD per 1M tokens, + RM conversion
estimate_cost(model, input_tokens, output_tokens) -> float | None
usage_from_result(result) -> TokenUsage     # sums usage_metadata across messages
```

Vision triggers are word-stem based (`scratch`, `colour`, `photo`, `look`, `dent`,
`crack`, `wear`, `picture`, `image`, `condition`, `damage`…) plus Malay and
Chinese equivalents, since the store is trilingual. Bare `see` and `show` are
deliberately excluded — they are the two commonest verbs in a buying conversation
("show me the link", "see you later") and including them fired on most turns,
giving back the entire saving.

The hinge for the fallback is the **description**, not the card: a card built
from name and price alone says nothing about what the item looks like, so a
listing with no description still gets its photos every turn.

# Test-Driven Development (TDD) Scenarios

- [x] **S1:** the card renders name/price/condition/description; absent fields vanish.
- [x] **S2:** a long description is trimmed to a bounded length.
- [x] **S3:** an ordinary turn ("can you do RM80?") carries the card and **zero** image parts.
- [x] **S4:** a visual question ("any scratches on the back?") attaches the images.
- [x] **S5:** a buyer-uploaded photo is always attached, whatever the text says.
- [x] **S6:** Malay/Chinese visual questions trigger vision too.
- [x] **S7:** history is capped at `AGENT_HISTORY_TURNS`.
- [x] **S8:** `estimate_cost` is right for a known model and None for an unknown one.
- [x] **S9:** `usage_from_result` sums real `usage_metadata` and survives its absence.
- [x] **S10:** the eval scenario set loads, ids are unique, and every scenario
      declares an assertion it can actually fail.

# Implementation Files

- `backend/agent/knowledge.py` — the card + the vision decision
- `backend/agent/cost.py` — pricing table and usage extraction
- `backend/agent/bot.py` — `_build_messages` uses both
- `backend/agent/config.py` — `AGENT_HISTORY_TURNS`
- `backend/evals/{__init__,scenarios,runner}.py` — the harness
- `backend/tests/test_evals_scenarios.py` — scenario data is checked where it is free
- `mise.toml` — `eval:agent`
- `docs/adr/0020-item-knowledge-card-over-per-turn-vision.md`
