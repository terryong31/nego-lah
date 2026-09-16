---
id: SPEC-084
title: Server-Enforced Negotiation Ratchet
status: complete
priority: high
created: 2026-09-15
tags: [agent, negotiation, pricing, revenue]
assigned: agent
---

# Context & Objectives

`SELLER_PERSONA` rules 6-7 say a negotiation only moves DOWN, and `evaluate_offer` implements
that by anchoring its counter to `current_price` — "the LOWEST price you have already offered
in THIS conversation" — which the **model** is asked to pass.

It never does. Measured across a full eval run (SPEC-083), **13 of 13** `evaluate_offer` calls
arrived with `current_price=0`, so the anchor fell back to the listed price on every single
turn and the ratchet has never engaged in production. Both engines, cloud and local:

> Buyer: RM120? → Seller: "Best I can do for you right now is **RM165**."
> Buyer: actually RM110? → Seller: "**RM180** is already a fair price for it."

The seller conceded to RM165 and then withdrew the concession and re-quoted the list price.
To a buyer that reads as bad faith, and it is the failure
`negotiation-never-quotes-above-a-price-it-already-offered` exists to catch — it fails on
Gemini and Qwen alike.

Asking an LLM to carry conversational state as a tool argument is the bug. The server already
knows the answer: `evaluate_offer` writes every committed counter and acceptance to
`negotiated_price:{user_id}:{item_id}`, and `payment.pricing.active_negotiated_price` already
resolves "the lowest still-live price this buyer has been quoted" for the item card and for
checkout. `evaluate_offer` is the only one of those surfaces that does not read it back.

**Objective:** resolve the standing price server-side so the ratchet holds regardless of what
the model passes.

# Acceptance Criteria

- [x] **Server resolves the anchor:** `evaluate_offer` takes the standing price from
      `active_negotiated_price(user_id, item_id)` as well as the model's `current_price`.
- [x] **Lowest wins:** the anchor is the minimum of the listed price, the server's standing
      price, and a positive `current_price` — clamped into `[min_price, listed_price]`.
- [x] **Model omission is harmless:** with `current_price=0` (what the model actually sends)
      and a cached standing price, the counter still anchors to the standing price.
- [x] **Model cannot ratchet UP:** a `current_price` *above* the server's standing price does
      not raise the anchor — a hallucinated or optimistic argument cannot undo a concession.
- [x] **Still fail-safe:** no user/item context, or a Redis outage, falls back to today's
      behaviour (anchor = listed price) rather than raising.
- [x] **REJECT_FLOOR names the price to hold:** "Hold firm at the price you last quoted" asked
      the model to recall its own last quote, which is what it got wrong. The instruction now
      names the anchor — a price this buyer was already quoted out loud, so nothing is
      disclosed.
- [x] **Floor still holds:** the anchor can never sit below `min_price`, and no branch names it.
      An anchor sitting exactly *on* `min_price` still quotes no number at all, because there
      the number IS the floor (SPEC-044 A).
- [x] **The scenario passes:** `negotiation-never-quotes-above-a-price-it-already-offered`
      passes on both providers.

# Technical Design & Contracts

```python
# agent/tools/negotiation.py::evaluate_offer
from payment.pricing import active_negotiated_price

standing = active_negotiated_price(user_id, item_id)   # None when never quoted
candidates = [listed_price]
if current_price and current_price > 0:
    candidates.append(current_price)
if standing is not None:
    candidates.append(standing)
anchor = min(max(min(candidates), min_price), listed_price)
```

Invariant: the anchor is monotonically non-increasing across a conversation for a given
buyer+item, because every value that lowers it is one the server itself committed.

# TDD Scenarios

- [x] **S1:** `current_price=0` + cached standing price -> counter anchors to the standing
      price, not the listed price (the production bug, in one test).
- [x] **S2:** `current_price` higher than the cached standing price -> anchor stays at the
      standing price.
- [x] **S3:** `current_price` lower than the cached standing price -> the lower one wins.
- [x] **S4:** no cached price -> behaviour is unchanged from SPEC-047.
- [x] **S5:** a cached price below `min_price` is clamped up to the floor.
- [x] **S6:** a Redis failure degrades to the listed-price anchor instead of raising.
- [x] **S7:** an offer at or above the cached standing price is ACCEPTed.
- [x] **S8:** a below-floor lowball after a concession says "hold firm at <the conceded
      price>" — not the listed price, and never the floor. This is the eval transcript in
      one test.
- [x] **S9:** with the anchor clamped onto `min_price`, REJECT_FLOOR still quotes no number
      (`test_a_standing_price_at_the_floor_quotes_no_number_at_all` keeps passing).

# Implementation Files

- `backend/agent/tools/negotiation.py`
- `backend/tests/test_negotiation_ratchet.py`
