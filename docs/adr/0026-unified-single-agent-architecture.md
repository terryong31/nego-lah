# ADR-0026: Unified Single-Agent Architecture with Direct Tool Calling

- Status: Accepted
- Date: 2026-09-16

## Context
In SPEC-000, the conversational agent was designed as a multi-agent supervisor graph where `Customer Agent` coordinated two specialized sub-agents: `ItemAgent` (catalog inspection) and `StripeAgent` (payment pipeline).

In practice, this nested architecture produced several production issues:
1. **Multi-Agent Latency Tax:** Every delegation required 3 to 5 sequential LLM network hops: Supervisor call -> Sub-agent call -> Sub-agent synthesis -> Supervisor synthesis. End-to-end turn times averaged 4–8 seconds.
2. **Context Loss:** Sub-agents ran in isolated prompt contexts, leading to lost item IDs and necessitating complex string-parsing workarounds from conversation history.
3. **Token Inefficiency:** Multi-agent prompt nesting broke prompt-prefix caching and multiplied token billing on every turn.
4. **Local Hardware Starvation:** With a single-concurrency lease on the local Apple Silicon M5 instance (Qwen 35B), holding leases across multi-agent loops starved concurrent requests and forced excessive overflow to cloud Gemini.

## Decision
1. **Eliminate Sub-Agent Indirection:** Remove the intermediate `ItemAgent` and `StripeAgent` ReAct graphs from the live conversation path.
2. **Direct Tool Binding:** Bind all domain tools (`tools.items`, `tools.payment`, `tools.negotiation`, `tools.orders`, `transfer_to_human`) directly to the unified `Customer Agent`.
3. **Retain External Web Search:** Keep `web_search` as an active direct tool to preserve context lookup capabilities when needed.
4. **Simplified Streaming:** Directly map SSE status notifications from emitted tool names (`create_checkout_link`, `collect_shipping_info`, `search_items`, etc.) without buffering or inspecting JSON argument strings.

## Consequences

### Positive
- **Latency Cut in Half:** Turn execution drops from 3–5 LLM round-trips to at most 1–2 calls (1 call if conversational/haggling, 2 if invoking a tool).
- **Prompt Caching Efficiency:** Unified static system prompt prefix enables Gemini / Claude context caching, slashing input token costs by 50%–80%.
- **Zero Sub-Agent Memory Fragmentation:** Item ID, negotiation concessions, and order context exist in one coherent working memory.
- **Architectural Simplicity:** Fewer compiled graphs, lower memory footprint on the 2 GB VPS, and cleaner testability.

### Negative / Trade-offs
- The primary agent now manages 11 tool schemas instead of 7 wrapper tools. Modern LLMs (Gemini 3.8 Flash, Qwen 3.6-35B) easily handle this tool volume without degraded accuracy.
