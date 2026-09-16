---
id: SPEC-089
title: Checkout Cannot Undercut the Standing Price
status: complete
priority: high
created: 2026-09-15
tags: [security, payment, negotiation, revenue]
assigned: agent
---

# Context & Objectives

`create_checkout_link` enforces one price rule: `agreed_price >= min_price`. That stops a
prompt-injected giveaway, which is what SPEC-036 was for. It does not stop the agent
*inventing a discount it was never authorised to give*.

Observed, with the SPEC-087 trace proving no tool ran on the turn:

```
[human] can you do RM1800?
[ai]    tool_calls=None
        "RM1800 is still a bit too low for the ASUS TUF Gaming A15.
         I can offer it at RM2300. How does that sound? 😊"
```

The item lists at RM2599 with a floor of RM2000. RM1800 is **below the floor**, so
`evaluate_offer` would have returned `REJECT_FLOOR` — no counter at all, hold at RM2599. The
agent conceded RM299 that the business rules say it had no authority to concede, and because
RM2300 clears `min_price`, checkout would have honoured it.

The floor check answers "is this above the absolute minimum?". The question it never asked is
"is this a price we actually offered?". SPEC-084 made the server the authority on the standing
price for counters; checkout is the only place that authority translates into money, and it
was the one place still taking the model's word for it.

**Objective:** money cannot leave below the price the server itself last committed to.

# Acceptance Criteria

- [x] **Ratchet enforced at checkout:** `create_checkout_link` refuses an `agreed_price` below
      `active_negotiated_price(user, item)`, falling back to the listed price when nothing has
      been negotiated.
- [x] **The authorised path still works:** a counter the tool committed (cached in Redis) is
      checkout-able at exactly that price.
- [x] **Paying more is always fine:** only undercutting is refused.
- [x] **Floor check unchanged:** the `min_price` rule still runs and still comes first, so its
      rejection wording and confidentiality are untouched.
- [x] **Discloses nothing:** the refusal names neither `min_price` nor the standing price — it
      tells the agent to run `evaluate_offer` and try again.
- [x] **Fails safe, not open:** if the standing price cannot be resolved, fall back to the
      listed price rather than skipping the check.

# Technical Design & Contracts

```python
# agent/tools/payment.py::create_checkout_link, after the min_price check
standing = active_negotiated_price(user_id, item_id) or asking_price
if agreed_price < standing - 0.01:      # float tolerance on a currency amount
    return "PRICE NOT AUTHORISED: … call evaluate_offer first …"
```

Invariant: `agreed_price >= max(min_price, standing_price)` for every link ever issued.

# TDD Scenarios

- [x] **S1:** the observed case — RM2300 with nothing negotiated on a RM2599 listing — is
      refused, even though it clears the floor.
- [x] **S2:** with a committed counter of RM2449, checkout at RM2449 succeeds.
- [x] **S3:** checkout below a committed counter is refused.
- [x] **S4:** checkout above the standing price succeeds.
- [x] **S5:** a below-floor price is still refused by the existing check, with its existing
      wording.
- [x] **S6:** the refusal names neither the floor nor the standing price.
- [x] **S7:** a resolver failure falls back to the listed price and refuses an undercut.

# Implementation Files

- `backend/agent/tools/payment.py`
- `backend/tests/test_checkout_price_authority.py`
