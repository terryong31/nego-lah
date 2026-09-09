---
id: SPEC-047
title: Human-Like Negotiation Concessions & Negotiated-Price Checkout
status: complete
priority: high
created: 2026-09-09
tags: [backend, negotiation, payment, agent]
assigned: agent
---

# Context & Objectives

Two negotiation-facing defects, both about the *number* the buyer ends up seeing:

1. **The agent concedes like a machine, not a haggler (TODO #43).**
   `evaluate_offer` splits the difference on every move:
   - a normal counter is the exact midpoint of `(offer, standing_price)`;
   - a *below-floor* lowball is answered with the exact midpoint of
     `(standing_price, min_price)` — a 50% cut of the remaining room toward the
     secret floor, handed over for any insulting offer.
   Counters also come out as `RM94.32`, `RM80.71` — nothing a real
   marketplace seller would ever type. Terry wants it to read like Carousell /
   FB Marketplace / eBay: **whole, round numbers** (…, 75, 80, 85, 90, 95),
   small moves, and **hold firm on a below-floor offer** — the buyer has to come
   up first, unless they genuinely prove need (the existing
   `assess_discount_eligibility` path).

2. **"Buy Now" ignores the negotiated price (TODO #44).**
   The chat-header and item-page **Buy Now** buttons both `POST /payment/checkout`,
   which charges `items.price` (the *listed* price) and never looks at the
   negotiated price the agent already cached in Redis
   (`negotiated_price:{user}:{item}`). A buyer haggles the agent down to RM900,
   the header shows RM900 (SPEC-041), they tap Buy Now — and Stripe charges
   RM1000. The agent's own pay-link tool (`create_checkout_link`) honours the
   deal; the button does not. Fix is backend-only — **no UI change** (Terry's call).

# Acceptance Criteria

- [x] **Below the floor** (`offered_price < min_price`): `evaluate_offer` holds.
      It returns a `REJECT_FLOOR:` result that tells the model to restate its
      last quote and not go lower, quotes **no** number, and never names the
      floor (SPEC-044 invariant preserved). Nothing is written to
      `negotiated_price:*` and `pending_discount` is not set.
- [x] **Above the floor, below the standing price**: the counter concedes
      `round_to_step((standing − offer) × COUNTER_CONCESSION_RATIO, COUNTER_STEP_RM)`
      off the standing price (halves round up). `COUNTER_CONCESSION_RATIO = 0.25`
      and `COUNTER_STEP_RM = 5.0` live in `agent/config.py` as tunable constants.
- [x] Every price the agent *quotes* (counter, standing price restated) is a
      whole ringgit — `RM90`, never `RM89.50` or `RM90.00`. The buyer's own
      offer is echoed back unrounded.
- [x] When the rounded concession is `0` (the buyer is within one step of the
      standing price), `evaluate_offer` returns a `HOLD:` result — restate the
      standing price, don't move this round — rather than a counter.
- [x] The **normal counter for above-floor offers is unchanged in spirit** —
      still meet-in-the-middle-ish — only the step size and rounding change. The
      midpoint-toward-floor concession for below-floor offers is **removed**.
- [x] Genuine-need path intact: a positive `extra_discount_percent` still lowers
      `adjusted_threshold` (never below `min_price`), so a buyer who earned a
      discount gets *accepted* nearer the floor — but a sub-floor offer is still
      held.
- [x] `POST /payment/checkout` charges `min(listed_price, active_negotiated_price)`
      when the buyer has a live negotiated price for that item, clamped to
      `>= min_price`. With no negotiated price it charges the listed price
      exactly as before.
- [x] The negotiated price feeding checkout is resolved by **one shared helper**
      (`payment/pricing.py::active_negotiated_price`) also used by
      `routes/items.py::_apply_discount` — the pending-payment lock price and the
      Redis `negotiated_price:*` entry, lowest wins.
- [x] `create_checkout_session` receives the resolved amount; the Stripe session
      also carries `item_name` in metadata and `customer_email` set to the
      buyer's account email (supports SPEC-048).
- [x] No regression in `test_agent_floor_confidentiality.py` invariants (the
      floor's value never appears in any `evaluate_offer` output).

# Technical Design & Contracts

### `agent/config.py`
```python
# SPEC-047 — counter-offer shaping. A counter concedes this fraction of the gap
# between the buyer's offer and our current standing price, snapped to a whole
# RM step, so quotes read like a real marketplace haggle (…, 85, 90, 95) and
# never RM94.32. Lower the ratio for a stickier agent, raise it for a softer one.
COUNTER_CONCESSION_RATIO = 0.25
COUNTER_STEP_RM = 5.0
```

### `agent/tools/negotiation.py::evaluate_offer`
- New helper `_round_to_step(value, step)` — nearest multiple, halves up
  (`math.floor(value / step + 0.5) * step`).
- `make_counter()` → `float | None`:
  ```
  gap        = anchor - offered_price
  concession = _round_to_step(gap * COUNTER_CONCESSION_RATIO, COUNTER_STEP_RM)
  if concession <= 0: return None
  counter = float(round(anchor - concession))
  return counter if offered_price < counter < anchor else None
  ```
- COUNTER branch: `None` → `HOLD:` result; otherwise `COUNTER:` with `RM{counter:.0f}`
  and `RM{anchor:.0f}`.
- Below-floor branch collapses to the existing no-number hold text
  (previously only used when the standing price was already at the floor):
  ```
  REJECT_FLOOR: Offer of RM{offered_price} is too low to accept. Hold firm at
  the price you last quoted and do not go lower. Do NOT state a minimum, a
  floor, or how low you can go.
  ```
  `counter` stays `None` → the Redis / `pending_discount` commit block is skipped.

### `payment/pricing.py` (new)
```python
def active_negotiated_price(user_id: str, item_id: str) -> float | None:
    """Lowest still-live price this buyer has been quoted for this item:
    a pending Stripe link's locked price, or evaluate_offer's cached
    counter/acceptance. None when neither exists."""
```
Moves the pending-payment + Redis lookup currently inlined in
`routes/items.py::_apply_discount` into one place; `_apply_discount` calls it
and keeps its own `< listed_price` gate.

### `routes/payment.py::checkout`
```python
listed = float(item['price'])
floor  = float(item.get('min_price') or listed)
negotiated = active_negotiated_price(user_id, item_id)
effective = min(listed, negotiated) if negotiated else listed
effective = max(effective, floor)          # defensive; evaluate_offer never commits below floor
price_cents = round(effective * 100)
```
`create_checkout_session(..., item_name=item['name'], customer_email=<account email>)`.

### `payment/pay.py::create_checkout_session`
New optional `customer_email: str | None` and `item_name` into `metadata`.
`stripe.checkout.Session.create(..., customer_email=customer_email or None,
metadata={'item_id':…, 'user_id':…, 'item_name':…})`.

# Test-Driven Development (TDD) Scenarios

- [x] **#43-1:** offer below `min_price` → result starts `REJECT_FLOOR:`,
      contains "Hold firm", no digits from the floor, `negotiated_price:*` unset,
      `pending_discount` None.
- [x] **#43-2:** standing 100, offer 60, floor 60 → `COUNTER: … RM90 …` (gap 40 ×
      0.25 = 10 → step 10).
- [x] **#43-3:** standing 90, offer 70 → `COUNTER: … RM85 …` (gap 20 × 0.25 = 5).
- [x] **#43-4:** standing 85, offer 82 → `HOLD:` (gap 3 × 0.25 = 0.75 → step 0).
- [x] **#43-5:** every quoted number in a COUNTER/HOLD result matches
      `/RM\d+(?!\.\d)/` — no decimal point after the amount.
- [x] **#43-6:** repeated below-floor lowballs (12 rounds, `current_price` fed
      back) never produce a "Counter with" line and never leak the floor.
- [x] **#43-7:** `extra_discount_percent=10`, standing 100, offer 90, floor 70 →
      ACCEPT (adjusted_threshold 90); offer 65 → still `REJECT_FLOOR:` hold.
- [x] **#43-8:** COUNTER commits the whole-number counter to `negotiated_price:*`
      and `pending_discount` (e.g. `"90.0"`).
- [x] **#44-1:** buyer with `negotiated_price:{u}:{i}` = 900, listed 1000 →
      `POST /payment/checkout` builds the Stripe session at 90000 cents.
- [x] **#44-2:** no negotiated price → session at the listed price, unchanged.
- [x] **#44-3:** negotiated price 500 but `min_price` 650 → clamped to 65000 cents.
- [x] **#44-4:** pending-payment lock at 800 and Redis entry at 850 →
      `active_negotiated_price` returns 800 (lowest live quote).
- [x] **#44-5:** `create_checkout_session` passes `customer_email` and
      `item_name` through to `stripe.checkout.Session.create`.
- [x] Existing `_apply_discount` behaviour (`routes/items.py`) unchanged —
      `test_routes_items_discount.py` stays green.

# Implementation Files

- `specs/SPEC-047-human-like-negotiation-and-negotiated-checkout.md` — this spec
- `docs/adr/0011-human-like-negotiation-concessions.md` — decision record
- `backend/agent/config.py` — `COUNTER_CONCESSION_RATIO`, `COUNTER_STEP_RM`; negotiation-strategy prompt item 9 rewritten per tool verb (ACCEPT / COUNTER / **HOLD** / REJECT_FLOOR — the last two carry no number, model must not invent a counter)
- `backend/agent/tools/negotiation.py` — `_round_to_step`, `make_counter`, `HOLD:` result, below-floor hold
- `backend/payment/pricing.py` — `active_negotiated_price` (new)
- `backend/routes/items.py` — `_apply_discount` delegates to the shared helper
- `backend/routes/payment.py` — `checkout` resolves the effective price + account email
- `backend/payment/pay.py` — `create_checkout_session` gains `customer_email`, `item_name` metadata
- `backend/tests/test_agent_tools_negotiation.py` — rewrite counter/reject expectations
- `backend/tests/test_agent_floor_confidentiality.py` — below-floor now holds, not counters
- `backend/tests/test_payment_pricing.py` — `active_negotiated_price` (new)
- `backend/tests/test_routes_payment.py` — negotiated-price checkout scenarios
