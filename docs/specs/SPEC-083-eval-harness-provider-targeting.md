---
id: SPEC-083
title: Eval Harness Provider Targeting
status: complete
priority: high
created: 2026-09-15
tags: [agent, evals, llm, tooling]
assigned: agent
---

# Context & Objectives

`evals/runner.py` (SPEC-059) is the only thing that scores the seller agent with numbers
instead of vibes. Two problems make it unable to answer the question now in front of it —
"how far behind Gemini is the self-hosted Qwen, and did changing anything help?"

1. **It cannot target the local model at all.** `main()` hardcodes `LLM_PROVIDER = "gemini"`,
   and `--model` only swaps *which Gemini*. Every number the harness has ever produced is a
   cloud number.
2. **The scenarios never had their item.** `run_scenario` passed
   `scenario.item["id"]` — `"eval-item-casio"` — down as a real item id. It is not a UUID,
   so every lookup raised `invalid input syntax for type uuid` and `evaluate_offer` answered
   "Cannot evaluate - item not found." Every negotiation and confidentiality number the
   harness could produce was scored against an agent with no listing and a dead tool.
3. **It is broken.** `main()` imports `_gemini_model` from `agent.llm_factory`, which was
   renamed to `_gemini_model_name`. The import is inside the function, so it survives
   collection and dies at runtime: `mise run eval:agent` currently raises ImportError before
   running a single scenario. `evals/runner.py` is in `[tool.coverage.run] omit`, so nothing
   caught it.

Targeting the local provider is not just an env flip. Since SPEC-081 the system prompt AND
the sampling temperature are both resolved from the `current_provider` ContextVar. Setting
`LLM_PROVIDER=local` alone leaves that ContextVar unset, so the run would use the local
*model* under the **cloud prompt** at the **cloud temperature** — measuring a configuration
that never runs in production.

**Objective:** let the harness pin either engine end-to-end, deterministically, and keep the
seam under test so a rename cannot silently break it again.

# Acceptance Criteria

- [x] **`--provider {cloud,local}`:** selects the engine; defaults to `cloud` so existing
      invocations and their numbers are unchanged.
- [x] **Whole-stack pinning:** the run pins `llm_factory.current_provider`, so the model,
      the system prompt (SPEC-081) and the temperature all resolve to the chosen engine.
- [x] **No overflow mid-run:** pinning bypasses the health probe and the lease, so a busy or
      flapping laptop cannot silently move half the scenarios to Gemini and make the
      comparison meaningless.
- [x] **Fails loudly:** with the local engine pinned and the tunnel down, scenarios error and
      are reported as failures rather than quietly passing on cloud.
- [x] **Import bug fixed:** `_gemini_model` -> `_gemini_model_name`.
- [x] **Scenarios get their listing:** `scenario.item` is served to both seams the listing
      reaches the agent by — the knowledge card in `bot._build_messages` and the row
      `evaluate_offer` reads for the floor — without seeding the real `items` table (which
      would make the eval depend on live inventory and on the `min_price` column privileges
      SPEC-036 revoked).
- [x] **All four client seams stubbed:** `connector.admin_supabase`, `connector.user_supabase`
      (used by `agent/tools/items.py`), `agent.tools.orders.admin_supabase` (bound at module
      level, so patching `connector` does not reach it), and `bot.get_item_details_for_context`.
- [x] **Non-item tables answer empty:** an orders or checkout scenario is not handed the
      pocket computer it did not ask for.
- [x] **Covered seam:** provider resolution and pinning live in `evals/providers.py`, which is
      NOT coverage-omitted and is unit-tested, unlike `runner.py`.
- [x] **Honest cost line:** a self-hosted run reports no per-token cost rather than
      "unknown — not in MODEL_PRICING", which reads like a missing price rather than a
      model that has none.

# Technical Design & Contracts

```python
# evals/providers.py  (covered, unit-tested)
CLOUD, LOCAL = "cloud", "local"
CHOICES = (CLOUD, LOCAL)

def resolve_provider(name: str) -> ProviderInfo   # -> local_provider_info() / cloud_provider_info()
def pinned_provider(info: ProviderInfo)           # contextmanager, sets/resets current_provider
def is_self_hosted(info: ProviderInfo) -> bool    # cost reporting
```

`runner.main()` resolves once, wraps the whole scenario loop in `pinned_provider(...)`, and
reports `info.model` + `info.hardware`.

Invariant: exactly one engine serves an entire eval run, and it is the one named on the
report header.

# TDD Scenarios

- [x] **S1:** `resolve_provider("local")` / `("cloud")` return the matching `ProviderInfo`;
      an unknown name raises rather than defaulting.
- [x] **S2:** inside `pinned_provider(local)`, `bot.customer_prompt_for(current_provider.get())`
      returns the LOCAL prompt and `customer_temperature_for` the local temperature — the
      whole SPEC-081 stack follows the pin.
- [x] **S3:** `pinned_provider` restores the previous value on exit, including on exception.
- [x] **S4:** the runner's argparse defaults to `cloud`, so existing runs are unchanged.
- [x] **S5:** `agent.llm_factory._gemini_model_name` exists and is importable — the exact
      rename that broke the harness — and `evals.runner` imports cleanly.
- [x] **S6:** with `scenario_item` applied, `evaluate_offer` returns a real verdict verb
      instead of "item not found", and an offer below `min_price` is not accepted.
- [x] **S7:** every builder method on the stub chains (`ConversationMemory.get_history`
      calls `.order()`, which used to raise inside the stub once per turn).
- [x] **S8:** all four client seams resolve to the stub inside the context manager.

# Implementation Files

- `backend/evals/providers.py` — provider resolution + pinning
- `backend/evals/fixtures.py` — scenario listing served without the database
- `backend/evals/runner.py` — `--provider`, pinning, report header, cost line, import fix
- `backend/tests/test_evals_providers.py`
- `backend/tests/test_evals_fixtures.py`
