---
id: SPEC-055
title: Cash-on-Delivery Refusal and First-Come-First-Served Policy
status: complete
priority: medium
created: 2026-09-09
tags: [agent, negotiation, policy, fulfilment]
assigned: agent
---

# Context & Objectives

The agent has no position on cash on delivery. Buyers ask for it constantly in the
Malaysian second-hand market, and with nothing in the persona the model improvises:
sometimes agreeing to a meet-up the platform cannot support, sometimes refusing
without offering a way forward. Neither answer is the seller's.

Two facts have to reach the buyer, in the agent's own voice:

1. **COD is not supported in-app.** There is no cash flow, no escrow and no order
   record for it — checkout is Stripe-only. A buyer who wants COD must be handed to
   Terry, who arranges it himself outside the platform.
2. **The platform is first-come-first-served.** Stock is claimed by *payment*, not by
   agreement. A pending COD arrangement holds nothing: if someone else pays for the
   item before the COD meet-up, that arrangement is automatically cancelled.

# Acceptance Criteria

- [x] `SELLER_PERSONA` carries a `DELIVERY & PAYMENT POLICY` section stating that COD
      is not handled in-app, that Terry arranges it, and that stock is FCFS until paid.
- [x] Asked for COD / meet-up / cash / "jumpa" / self-collect, the agent explains the
      policy, states the FCFS caveat, and calls `transfer_to_human` so Terry can take
      the arrangement — it does not simply refuse.
- [x] `transfer_to_human`'s docstring names the COD case, so the supervisor reaches for
      it rather than inventing an answer.
- [x] The FCFS caveat is stated whenever COD is discussed, not only on request: an
      unpaid arrangement is cancelled the moment another buyer pays.
- [x] The agent never promises a COD price, a meet-up time, or a place — those are
      Terry's to give.
- [x] The policy holds under pressure: repeating, insisting or claiming a previous COD
      deal does not move it (it sits under the same absolute-scope rules as the rest of
      the persona).
- [x] `COD_POLICY` is exported from `agent/config.py` as an editable knob, alongside the
      negotiation constants, so the wording is one edit rather than a prompt rewrite.

# Technical Design & Contracts

`backend/agent/config.py`

```python
COD_POLICY = """
DELIVERY & PAYMENT POLICY - COD IS NOT SUPPORTED IN-APP:
- Every order is paid through the Stripe checkout link and shipped. There is no
  cash-on-delivery, meet-up or self-collect flow in this app...
- ... call `transfer_to_human` so Terry can arrange it directly.
- FIRST COME FIRST SERVED: an item is only held once it is PAID...
"""

SELLER_PERSONA = """...""" + COD_POLICY + """..."""
```

The transfer reason passed for this case is `"Cash-on-delivery arrangement requested"`,
which is what lands in the admin's alert email, so Terry sees why before opening the
chat. No new tool, no schema change: COD is a handoff, and the handoff already exists.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1 (policy present):** `SELLER_PERSONA` contains the COD refusal, the
      instruction to transfer to Terry, and the FCFS cancellation rule.
- [x] **Scenario 2 (knob):** `COD_POLICY` is a non-empty string and is a substring of
      `SELLER_PERSONA`, so editing it edits the prompt.
- [x] **Scenario 3 (tool discoverability):** `transfer_to_human.__doc__` mentions cash
      on delivery, so the supervisor's tool selection sees it.
- [x] **Scenario 4 (transfer works for COD):** calling `transfer_to_human` with a COD
      reason disables the AI, writes the system notice and emails the admin.
- [x] **Scenario 5 (no floor leak):** the COD text states no minimum price and no
      discount — the confidentiality assertions in `test_agent_floor_confidentiality`
      still pass over the extended persona.

# Implementation Files

- `backend/agent/config.py` - `COD_POLICY`, spliced into `SELLER_PERSONA`
- `backend/agent/bot.py` - `transfer_to_human` docstring names the COD case
- `backend/tests/test_agent_cod_policy.py` - Scenarios 1-5
