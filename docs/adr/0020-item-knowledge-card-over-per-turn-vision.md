# ADR 0020: An Item Knowledge Card Instead of Re-Sending the Photos Every Turn

## Status
Accepted

## Context

`agent/bot._build_messages` attached up to two `image_url` parts to the buyer's message
whenever an `item_id` was in context. Not on the first turn — on **every** turn. A
twenty-turn haggle over one listing paid for forty image ingests, each billed at roughly
258 tokens plus vision prefill latency, to show the model something it had already seen.

What makes this waste rather than a trade-off is where `items.description` comes from: it
was written *from those same photos* by `image_analyzer.analyze()` when the listing was
created. The model was being handed a picture and a description of the picture,
simultaneously, on repeat.

Two smaller multipliers sat behind it. The transcript was replayed at a hard-coded 50
messages per turn, and a ReAct turn re-sends its whole context on every step, so history
and persona are paid for several times within a single buyer message.

## Decision

**Send what we already know, not what we already showed.** `agent/knowledge.py` renders a
compact card — name, listed price, condition, trimmed description — and that goes in the
system context every turn. Missing fields are omitted rather than rendered as `None`,
because a model handed `Condition: None` reads it out to the buyer.

**Photos become conditional, on three triggers.** A buyer upload (always — cost control
must never silently drop a photo the buyer chose to send); a listing with no description
(the photos are then the only visual information there is, so behaviour is unchanged); or
a visual question, matched on word stems across all three of the store's languages.

**The hinge is the description, not the card.** An early version keyed the fallback on "is
the card non-empty", which was wrong: a card built from name and price alone says nothing
about what the item looks like, and would have silently stopped sending photos for
listings that had no description at all.

**`see` and `show` are excluded from the triggers.** They are the two commonest verbs in a
buying conversation — "show me the link", "see you later" — and including them fired on a
large share of ordinary turns, giving back the entire saving. The sentences that genuinely
want a photo name one ("show me the *picture*"), and are caught by the object instead. The
list errs generous otherwise: a false positive costs one turn's images, while a false
negative has the agent claim it cannot see something it could have looked at.

**`AGENT_HISTORY_TURNS` replaces the hard-coded 50**, defaulting to 20. Safe because
`evaluate_offer` keeps the negotiated floor in Redis rather than in the transcript, so
falling off the end of the window cannot lose the negotiation's state.

**Cost becomes measurable.** `agent/cost.py` reads the provider's own `usage_metadata` —
summed across every LLM step of a turn, since a tool-using turn is several calls and
reading only the last would under-report most of it — and prices it. Unknown models return
`None` rather than a guess, because a wrong cost gets quoted as fact.

## Consequences

- **Ordinary turns carry zero images.** The saving scales with conversation length, which
  is exactly where the old behaviour was worst.
- **The trigger list is a maintenance surface.** A buyer phrasing a visual question in a way
  the stems miss gets an answer from the description instead of the photo. `evals/` is
  where that regression would show up.
- **Listings without descriptions are unchanged.** They keep paying for vision every turn —
  correctly, since nothing else describes them. Writing descriptions is now a cost lever.
- **A second cache for the per-turn item lookup was considered and dropped.** It would have
  saved one indexed read — latency, not tokens — at the price of a second invalidation path
  beside `invalidate_item_cache`'s six call sites, where missing one means quoting a
  **stale price** to a buyer. Not a trade worth making days before launch.

## On ragas

TODO 45 asked for ragas specifically. It was attempted and rejected on evidence:

1. Every release through 0.4.3 hard-imports `langchain_community.chat_models.vertexai`,
   which langchain-community 0.4.x removed. `import ragas` raises before any metric is
   reachable — this is not a configuration problem, it is a hard incompatibility with the
   langchain stack this repo runs.
2. Adding it to the lockfile *at all* dragged production packages backwards — `rich`
   15.0.0 → 14.3.4, `openai` 3.7.0 → 3.3.0 — because uv resolves one version per package
   across every dependency group, including opt-in ones. Shipping a downgraded production
   image for a tool that cannot import is not a trade worth making.

What replaced it: the deterministic assertions (which are what the exit code is based on,
and which ragas was never going to provide) plus a short LLM judge for answer relevancy,
built on a dependency the repo already has. `_judge_relevancy` is the seam — if a ragas
release ever drops that import, swap its body and the report picks the score up unchanged.

## On switching to a cheaper model

TODO 52 also asks whether to move to a lighter tier. That is now a measurement rather than
a guess: `mise run eval:agent -- --model <other>` runs the same scenarios and prints pass
rate per category beside cost per conversation. The number to watch is not the price — it
is the **confidentiality** row. A model 60% cheaper that recites `min_price` to a buyer
loses more on one sale than it saves in a month, which is why those scenarios probe the
floor from four angles and why the report puts both figures on the same screen.

The prices in `MODEL_PRICING` are dated (`PRICES_SOURCED`) and printed with every report,
because they will go stale and someone will otherwise quote them as current.

## References
- `specs/SPEC-059-agent-cost-reduction-and-evaluation.md`
- ADR 0003 (dual-provider multimodal LLM failover), ADR 0007 (hybrid edge/cloud router) —
  the self-hosted model is priced at zero marginal cost per token for the reason given there
- SPEC-047 / ADR 0011 — why the floor lives in a tool and not in the prompt
