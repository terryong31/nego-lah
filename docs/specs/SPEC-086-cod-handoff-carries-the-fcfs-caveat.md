---
id: SPEC-086
title: COD Handoff Carries the FCFS Caveat
status: complete
priority: medium
created: 2026-09-15
tags: [agent, policy, tools, llm]
assigned: agent
---

# Context & Objectives

SPEC-055 requires that whenever cash-on-delivery comes up the agent says two things: Terry
will arrange it, **and** items are first come, first served — nothing is reserved by talking
about it, only a paid order holds the item. The second half is the part that protects the
buyer from travelling to a meet-up for something already sold.

That requirement lives in `COD_POLICY`, inside the persona. Gemini follows it; the
self-hosted Qwen does not. Measured (SPEC-083, `policy-cod-is-handed-to-a-human-with-fcfs-stated`):

> Buyer: can I COD? meet up at KL sentral and pay cash
> Seller: "Terry will be with you shortly to sort out the COD details. Just wait here! 👍"

It called `transfer_to_human` correctly and then paraphrased the tool's return string and
nothing else. A rule two hundred lines up a persona lost to the sentence the model had just
been handed.

This is the same lesson as SPEC-084: a tool result is the most specific and most recent
instruction the model has, so anything that must be said belongs in the tool result rather
than in a policy the model is trusted to remember.

**Objective:** make the COD handoff itself carry the caveat.

# Acceptance Criteria

- [x] **The tool says it:** `transfer_to_human` returns the FCFS instruction when the transfer
      is a COD / meet-up / cash / self-collect case.
- [x] **Detected from the reason:** matched against `reason` and `summary`, so it fires on the
      persona's own wording ("Cash-on-delivery arrangement requested") and on a free-text
      summary.
- [x] **Only for COD:** an ordinary "customer asked for a human" transfer is unchanged — the
      caveat is about meet-ups, and attaching it to a dispute would be noise.
- [x] **Relayed, not dictated:** the tool instructs the agent to say it in its own words, so
      the trilingual adaptation of SPEC-080 still applies.
- [x] **The scenario passes on both providers.**

# Technical Design & Contracts

```python
# agent/bot.py
COD_TRANSFER_KEYWORDS = ("cod", "cash on delivery", "cash-on-delivery", "cash",
                         "meet", "jumpa", "self-collect", "self collect", "collect")

def _is_cod_transfer(reason: str, summary: str) -> bool: ...

# appended to the return value when it is:
"Also tell the buyer, in your own words: items here are FIRST COME FIRST SERVED. "
"Nothing is reserved by talking about it — only a PAID order holds the item — so if "
"someone else pays before the meet-up happens, the arrangement is off."
```

# TDD Scenarios

- [x] **S1:** a COD reason returns a string containing "first come" and "paid".
- [x] **S2:** a meet-up / self-collect / cash phrasing triggers it too.
- [x] **S3:** the caveat is detected from `summary` when `reason` is generic.
- [x] **S4:** a plain "customer requested human seller" transfer does NOT carry it.
- [x] **S5:** the handoff still disables the AI, flags admin intervention and alerts Terry —
      the caveat is additive, not a rewrite.
- [x] **S6:** the returned text names no price, floor or discount.

# Implementation Files

- `backend/agent/bot.py`
- `backend/tests/test_cod_handoff_caveat.py`
