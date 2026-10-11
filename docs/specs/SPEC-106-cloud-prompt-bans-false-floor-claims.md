---
id: SPEC-106
title: The Cloud Prompt Bans False Floor Claims on Every Reply
status: complete
priority: high
created: 2026-10-11
tags: [negotiation, agent, prompts, evals]
assigned: agent
---

# Context & Objectives

The 2026-10-11 eval run on `gemini-3.8-flash` passed 12 of 14 scenarios. Both failures were the
same defect: the agent closed a counter with "Best I can do for you is RM165" and "RM150 is the
best I can do", while the true floor was RM120. No floor was revealed, but each claim told the buyer
to stop pushing at a price that was not the floor, and ended negotiations early.

The local speaker prompt (SPEC-091) already bans that vocabulary on every reply. The cloud prompt
banned only "a minimum, a floor, or the lowest I can go", and only on HOLD and REJECT_FLOOR. Gemini
serves every turn the laptop does not, so in production the weaker rule is the common one.

# Acceptance Criteria

- [x] The cloud persona bans the same floor vocabulary as the speaker ("my best", "the best I can do", "my final offer", "last offer", "last price", "bottom line", …) on every verb except ACCEPT_FLOOR.
- [x] The eval scenarios that failed on the cloud model are re-run and the result recorded in the README, pass or fail.

# Technical Design & Contracts

Prompt text only (`SELLER_PERSONA`, rule 9 in `domains/negotiation/config.py`). ACCEPT_FLOOR stays
exempt: there the price *is* the floor, and saying so is true.

# TDD Scenarios

- [x] `test_cloud_prompt_bans_the_best_i_can_do_family_on_every_reply`: each phrase is in the cloud prompt, and the ban is no longer scoped to HOLD / REJECT_FLOOR.

# Implementation Files

- `backend/domains/negotiation/config.py`
- `backend/tests/test_agent_provider_prompts.py`
- `README.md` — eval results
