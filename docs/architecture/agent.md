# Agent Architecture

How one buyer message becomes a reply. Living document; code lives in
`backend/domains/negotiation/`. Decisions: [ADR-0003](../adr/0003-dual-provider-multimodal-llm-failover.md),
[ADR-0007](../adr/0007-hybrid-edge-cloud-llm-load-balancer.md),
[ADR-0011](../adr/0011-human-like-negotiation-concessions.md),
[ADR-0020](../adr/0020-item-knowledge-card-over-per-turn-vision.md),
[ADR-0021](../adr/0021-agent-turns-outlive-their-http-response.md),
[ADR-0024](../adr/0024-what-a-tool-hands-back-and-when-the-buyer-sees-it.md),
[ADR-0026](../adr/0026-unified-single-agent-architecture.md).

## 1. Choosing a model (`llm_factory.py`)

Each turn picks its provider **once**, in `hybrid_llm_session()`, and pins it in a `ContextVar`
so a turn never switches model halfway.

```text
probe local model (GET /models, 1.5 s timeout, result cached in Redis 30 s)
├── unhealthy ───────────────────────────────► Gemini (gemini-3.8-flash)
└── healthy → SET llm:qwen:busy NX EX 45 (token-owned lease)
     ├── acquired ─► Qwen3.6-35B-A3B on the M5, over Cloudflare Tunnel
     └── held ─────► Gemini, no waiting
```

The M5 serves one generation stream at full speed, so it is treated as a pool of exactly one.
The lease TTL is a backstop for a worker that dies mid-turn; normally the lease is released in a
`finally` by the token that took it.

## 2. Running the turn (`bot.py`)

The pinned provider decides which of two shapes the turn takes:

| Provider | Shape | Why |
|----------|-------|-----|
| **Gemini** | One LangGraph ReAct agent (`create_react_agent`) with every tool bound directly. | A single agent replaced a supervisor with two sub-agents, cutting 3–5 sequential model calls per delegated turn ([SPEC-079](../specs/SPEC-079-unified-single-agent-architecture.md)). |
| **Local Qwen** | **Decide, then speak** ([SPEC-091](../specs/SPEC-091-local-decide-then-speak-agent.md)): a decider that sees a compact brief and the tool schemas picks one tool; the server runs it; a speaker with **no tools bound** phrases the result in persona. | The 3B-active model stops calling tools once its window holds prior chat prose. Splitting routing from talking took tool selection from 3/7 to 7/8 on the measured turn set. |

Both shapes use the same tools, the same request context and the same output guards, so they
cannot disagree about a price.

## 3. Tools (`tools/`)

| Group | Tools |
|-------|-------|
| Catalog | `get_item_info`, `search_items`, `list_all_items` |
| Negotiation | `evaluate_offer`, `assess_discount_eligibility` |
| Payment & orders | `create_checkout_link`, `cancel_payment_link`, `collect_shipping_info`, `check_user_orders` |
| Context | `web_search` |
| Escalation | `transfer_to_human` (COD, meet-ups, disputes, "let me talk to a person") |

Tools read the current user and item from `ContextVar`s set at the start of the turn
(`context.py`), never from arguments the model supplies.

## 4. Rules the server enforces, not the prompt

A prompt is a request; these are guarantees.

- **The floor is invisible.** `min_price` is read only inside `evaluate_offer`, under the service
  role, and is never in a prompt or a response.
- **Prices only move one way.** The standing offer is stored per buyer and item; a counter can
  never rise above it ([SPEC-084](../specs/SPEC-084-server-enforced-negotiation-ratchet.md)) and
  checkout cannot undercut it ([SPEC-089](../specs/SPEC-089-checkout-cannot-undercut-the-standing-price.md)).
- **Concessions look human.** A counter concedes a fixed fraction of the gap and snaps to a whole
  RM step (`COUNTER_CONCESSION_RATIO`, `COUNTER_STEP_RM` in `config.py`).
- **Only server-issued payment links reach the buyer.** `link_guard.py` strips every link that
  is not the exact URL `create_checkout_link` stored ([SPEC-088](../specs/SPEC-088-payment-links-must-be-server-issued.md)).

## 5. Context and cost

- **History:** the last `AGENT_HISTORY_TURNS` (20) messages from `messages`, with tool calls from
  the last `AGENT_TOOL_TRACE_TURNS` (6) replayed so the model sees what it already did
  ([SPEC-087](../specs/SPEC-087-replay-tool-calls-in-agent-history.md)).
- **Images:** the item's photos are sent only when the turn needs them; otherwise the text
  description generated from those photos stands in ([ADR-0020](../adr/0020-item-knowledge-card-over-per-turn-vision.md)).
- **Cost:** `cost.py` prices each turn from the provider's own token counts. The eval harness in
  `backend/evals/` reports it alongside quality (`mise run eval:agent`).

## 6. Lifecycle

A turn runs as a detached task: if the buyer closes the tab, the turn still finishes and the
reply is saved ([ADR-0021](../adr/0021-agent-turns-outlive-their-http-response.md)). Replies
stream to the browser over SSE and are fanned out to every worker through Redis pub/sub. On
shutdown the server waits up to `SHUTDOWN_TURN_GRACE_SECONDS` (20 s) for in-flight turns.
