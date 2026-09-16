---
id: SPEC-079
title: Unified Single-Agent Architecture with Direct Tool Calling
status: complete
priority: high
created: 2026-09-14
tags: [agent, architecture, langgraph, latency, cost]
assigned: agent
---

# Context & Objectives

The negotiation engine previously used a multi-agent supervisor pattern where `Customer Agent` (Supervisor) delegated tasks to `ItemAgent` and `StripeAgent` via wrapper tools (`call_item_agent`, `call_stripe_agent`).

This nested ReAct pattern incurred a severe multi-agent latency and token penalty:
1. **Cascading LLM calls:** 3 to 5 sequential LLM invocations per turn just to execute simple database queries or create Stripe links.
2. **Context resolution hacks:** `call_stripe_agent` had to prompt `item_agent` with raw history text to recover missing item IDs via string manipulation.
3. **Token & latency overhead:** Repeated system prompts and schemas bloated token usage, degraded TTFT, and held the local Qwen lease for 5–10 seconds per turn.

**Objective:**
Flatten the architecture by eliminating intermediate sub-agents and binding all domain tools directly to the unified `Customer Agent`. Retain `web_search` for external context. Restructure architectural documentation into categorized domains (`agent/`, `system/`, `db/`).

# Acceptance Criteria

- [x] **Direct Tool Binding:** `customer_tools` in `agent/bot.py` binds catalog (`get_item_info`, `search_items`, `list_all_items`), payment (`create_checkout_link`, `cancel_payment_link`, `collect_shipping_info`, `web_search`), negotiation (`evaluate_offer`, `assess_discount_eligibility`), orders (`check_user_orders`), and escalation (`transfer_to_human`) directly to the customer agent.
- [x] **Real-time SSE Status:** `chat_stream` maps direct tool calls (`create_checkout_link`, `collect_shipping_info`, `search_items`, etc.) directly to user-friendly SSE progress indicators without intermediate arg parsing.
- [x] **External Web Search Retained:** `web_search` remains an active tool for contextual queries.
- [x] **Backward Compatibility:** Legacy helper functions remain importable so existing test suites and fixtures remain compatible.
- [x] **Documentation Categorization:** `docs/architecture/` organized into `agent/`, `system/`, and `db/` with clear navigation in `docs/architecture/README.md`.
- [x] **Test Coverage Gate:** Backend test suite passes with total coverage ≥88%.

# Technical Design & Contracts

```python
# Direct Tools bound on Customer Agent in agent/bot.py:
customer_tools = [
    get_item_info,
    search_items,
    list_all_items,
    create_checkout_link,
    cancel_payment_link,
    collect_shipping_info,
    evaluate_offer,
    assess_discount_eligibility,
    web_search,
    check_user_orders,
    transfer_to_human,
]
```

### Realtime SSE Status Mapping
- `create_checkout_link` -> `"Generating payment link..."`
- `cancel_payment_link` -> `"Cancelling your payment link..."`
- `collect_shipping_info` -> `"Saving your shipping details..."`
- `get_item_info`, `search_items`, `list_all_items` -> `"Understanding the item..."`
- `check_user_orders` -> `"Checking your orders..."`
- `evaluate_offer` -> `"Evaluating your offer..."`
- `web_search` -> `"Searching the market..."`
- `assess_discount_eligibility` -> `"Checking discounts..."`
- `transfer_to_human` -> `"Connecting to human seller..."`

# TDD Scenarios

- [x] **S1: Direct tool status emission:** Verify that `chat_stream` emits the expected status string when direct tools (`create_checkout_link`, `collect_shipping_info`, `search_items`) are called in tool call chunks.
- [x] **S2: Tool bindings:** Verify that `_select_customer_model` binds all 11 direct tools to the customer agent model.
- [x] **S3: End-to-end coverage:** All existing agent and tool tests pass without regression; coverage remains ≥88%.

# Implementation Files

- `backend/agent/bot.py`
- `backend/tests/test_agent_bot.py`
- `docs/adr/0026-unified-single-agent-architecture.md`
- `docs/architecture/README.md`
- `docs/architecture/SPEC-000-system-architecture.md`
- `docs/architecture/agent/README.md`
- `docs/architecture/system/README.md`
- `docs/architecture/db/README.md`
