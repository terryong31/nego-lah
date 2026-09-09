# 11. Human-Like Negotiation Concessions

- Status: Accepted
- Date: 2026-09-09
- Deciders: Terry (owner), AI Agent
- Relates to: SPEC-047; revises the concession mechanics of SPEC-044 (the floor-confidentiality invariant is kept)

## Context

`evaluate_offer` (the agent's price-decision tool) computed every concession as
an exact midpoint:

- a **normal counter** = `(offer + standing_price) / 2`;
- a **below-floor lowball** = `(standing_price + min_price) / 2` — half the
  remaining room toward the secret floor, conceded on the first insult.

Two problems:

1. **It doesn't read like a person.** Midpoints produce `RM94.32`, `RM80.71`.
   No one selling on Carousell, FB Marketplace or eBay types that. Buyers notice,
   and it makes the agent feel like a pricing script (which it is).
2. **It gives ground it shouldn't.** A buyer who offers RM1 for an RM100 item
   gets a RM85 counter for free. The correct move on a bad-faith lowball is to
   hold — the *buyer* has to come up.

SPEC-044 introduced the below-floor counter deliberately, to stop a bare "no"
from leaving the model with "nothing to say, so it invents a number" and to keep
the counter approaching the floor asymptotically so it never discloses it. That
reasoning is real but it optimised for the wrong thing: a below-floor offer
doesn't deserve a concession at all, and the model *does* have something to say —
"that's the best I can do" at its last quote.

## Decision

1. **Below the floor → hold.** `evaluate_offer` returns a `REJECT_FLOOR:` result
   instructing the model to restate its last quote and not go lower. It quotes
   **no number** and never names the floor — the SPEC-044 confidentiality
   invariant and its tests are unchanged. Nothing is committed to
   `negotiated_price:*`.

2. **Above the floor → concede a rounded fraction of the gap.**
   `counter = standing − round_to_step((standing − offer) × 0.25, RM5)`, halves
   rounding up. The ratio (`COUNTER_CONCESSION_RATIO`) and step
   (`COUNTER_STEP_RM`) are named constants in `agent/config.py`. If the rounded
   concession is `0` (buyer within one step), the tool returns `HOLD:` — restate
   the standing price this round — instead of a counter.

3. **All agent-quoted prices are whole ringgit.** The buyer's own offer is
   echoed back unrounded; every number the agent *proposes* is an integer, and
   counters land on multiples of RM5.

4. **Genuine need is unchanged.** `assess_discount_eligibility` →
   `extra_discount_percent` still lowers the acceptance threshold (never below
   `min_price`), so a buyer who earns a discount is *accepted* closer to the
   floor. A sub-floor offer is still held regardless.

Normal above-floor counters keep their meet-in-the-middle character — only the
step size and rounding change. `0.25` was chosen so a typical opening gap
(RM30–40 on a ~RM100 item) yields a RM10 first move, then RM5 moves as the gap
closes — the rhythm of an actual haggle.

## Consequences

- **Positive:** Quotes read like a marketplace seller. Bad-faith lowballs cost
  nothing and don't walk the price toward the floor. The concession curve is a
  two-line tunable, not a rewrite, if Terry wants it softer/stickier later.
- **Negative:** On a genuine below-floor offer from someone who can't articulate
  why they need the discount, the agent will feel firm — arguably too firm. The
  `assess_discount_eligibility` path is the intended pressure-release valve; if
  buyers hit the wall too often we revisit the ratio or the eligibility rubric.
- **Neutral:** SPEC-044's "counter approaches the floor asymptotically" property
  is now moot — there is no below-floor counter to leak anything.
- **Risk:** A model with a hard "no" can still stall a conversation. Mitigated by
  the `HOLD:`/`REJECT_FLOOR:` results carrying an explicit instruction to
  restate the last quote, so the model always has a concrete line to deliver.
