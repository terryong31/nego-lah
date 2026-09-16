---
id: SPEC-041
title: Real-Time Discount SSE Signal and Item Cache
status: complete
priority: high
created: 2026-09-06
tags: [backend, frontend, sse, negotiation, performance]
assigned: agent
---

# Context & Objectives

Two separate but related problems:

1. **N×1 item API calls per chat session (performance):** Every SSE turn in `pages/chat.vue` re-fetches `/items/{id}` to refresh the pinned header — including the `discounted_price` field. A buyer who sends 10 messages triggers 10 identical fetches. The item data is static for the duration of a chat; only `discounted_price` changes, and only when the agent explicitly offers a deal.

2. **Price-cut UX lag (real-time):** The agent's `evaluate_offer` tool writes the negotiated price to Redis the moment it decides to counter or accept. The AI response then streams to the browser. But the frontend discovers `discounted_price` only on the *next* items API poll — meaning the buyer reads "How about RM900?" while the price chip still shows RM1025. The discount should light up everywhere the instant the tool commits it, not one round-trip later.

**Solution:** fetch the item **once** on chat open, cache it in a shared item store, and have the backend emit a `data-discount` SSE event immediately after the tool writes to Redis. The frontend patches the store on that event. `chat.vue`'s header pin and `ItemCard.vue` read the store directly and become reactive to the patch with no extra work; `pages/items/[id].vue` fetches through the same store (so a same-tab-session cache hit skips the API call too) and re-renders from live store state.

# Acceptance Criteria

- [x] `GET /items/{id}` is called **exactly once** per chat page load; subsequent AI turns never trigger it.
- [x] When `evaluate_offer` sets a negotiated price, a `data-discount` SSE frame is emitted in the same streaming response **before the next text token**.
- [x] On receiving `data-discount`, the item store patches `discountedPrice` on the cached item; the price chip in the chat header, item listing cards, and item detail page all update reactively with no API call.
- [x] If the buyer opens the chat and a Redis entry already exists (returning session), the initial item fetch already includes `discounted_price`; the store is seeded correctly and the strikethrough renders immediately on load.
- [x] The `data-discount` SSE event exposes **only** `discounted_price` (a number) — no `user_id`, `item_id`, internal keys, or model metadata.
- [x] No regression to the existing `data-provider` SSE frame or any other stream event.

# Technical Design & Contracts

### Backend — discount event queue (ContextVar)

A new `ContextVar[float | None]` called `pending_discount` is added to `agent/context.py` (alongside the existing `item_id` and `user_id` vars). When `evaluate_offer` commits a price to Redis it also sets `pending_discount` to `active_price`.

The SSE stream loop in `routes/chat.py` drains `pending_discount` after each chunk from the LangGraph stream:

```python
discount = pending_discount.get()
if discount is not None:
    pending_discount.set(None)
    yield _sse({"type": "data-discount", "id": "discount", "data": {"discounted_price": discount}})
```

This keeps the tool decoupled from the wire protocol — the tool writes to a ContextVar, the route owns the SSE shape.

### SSE wire event

```json
{
  "type": "data-discount",
  "id": "discount",
  "data": { "discounted_price": 900.0 }
}
```

Emitted at most once per streaming turn (the first time `evaluate_offer` commits a price in that turn). If multiple tool calls happen in one turn, the lowest committed price wins (ContextVar always stores the latest write; `evaluate_offer` only writes when moving the price down).

### Frontend — `useItemStore`

Implemented as a `useState`-backed singleton composable (`frontend/app/stores/item.ts`), not Pinia — Pinia is not a registered Nuxt module in this project, and `useState` gives the same SSR-safe shared reactive state this design needs without adding a new dependency.

```ts
interface ItemState {
  item: StoreItem                 // full item object from API
  discountedPrice: number | null  // null = no active discount
}

// keyed by item_id to support multiple tabs / future multi-item chats
const items = useState<Map<string, ItemState>>('item-store', () => new Map())
```

**Actions:**
- `fetchIfMissing(itemId)` — calls `GET /items/{id}` only if the store has no entry for that ID. Called once in `chat.vue` `onMounted`.
- `refetch(itemId)` — unconditionally re-fetches and overwrites the cache even if an entry exists; used by `pages/items/[id].vue`'s 409 "just sold" retry, where `fetchIfMissing`'s dedup would otherwise leave the page stuck showing stale data.
- `applyDiscount(itemId, price)` — patches `discountedPrice` in place; called by `useChat`'s (`@ai-sdk/vue`) own top-level `onData` option in `chat.vue` when a `data-discount` frame arrives. (`onData` is a `useChat` option, not a transport one — it must NOT be nested inside `DefaultChatTransport`'s options, and the AI SDK invokes it once per data part, never with an array.)
- `getItem(itemId)` — returns the raw `{ item, discountedPrice }` cache entry, or `undefined`.
- `effectivePrice(itemId)` / `hasDiscount(itemId)` / `discountPercent(itemId)` — itemId-keyed getters that satisfy this store's own contract (see Scenarios 5–6). Real page components don't call these directly.

**Component wiring:** `chat.vue`, `ItemCard.vue`, and `pages/items/[id].vue` each read `getItem(itemId)` and build a `{ price, discounted_price }`-shaped object (the cached item overlaid with the live `discountedPrice`), then pass that to the existing `~/utils/pricing.ts` helpers (`effectivePrice`, `hasDiscount`, `discountPercent`) — so there's exactly one place the discount math itself lives, and all three surfaces render it identically.

# Test Scenarios

- [x] **Scenario 1 (backend):** A streaming turn where `evaluate_offer` accepts at RM900 emits exactly one `data-discount` frame with `{"discounted_price": 900.0}` before the next `text-delta`.
- [x] **Scenario 2 (backend):** A turn where no tool sets a negotiated price emits zero `data-discount` frames.
- [x] **Scenario 3 (backend):** `pending_discount` ContextVar is isolated per async request — two concurrent turns with different prices do not bleed into each other. Covered both sequentially (same connection, back-to-back turns) and with genuinely concurrent `asyncio.gather`'d requests.
- [x] **Scenario 4 (frontend, Vitest):** `fetchIfMissing` called twice with the same item ID makes exactly one HTTP call.
- [x] **Scenario 5 (frontend, Vitest):** `applyDiscount` updates `discountedPrice`; `effectivePrice` returns the discounted value; `hasDiscount` returns `true`.
- [x] **Scenario 6 (frontend, Vitest):** On load with a pre-discounted item (`discounted_price` in API response), `effectivePrice` reflects the discount without any SSE event.

# Implementation Files

**Backend**
- `backend/agent/context.py` — `pending_discount: ContextVar[float | None]`
- `backend/agent/tools/negotiation.py` — sets `pending_discount` alongside the Redis write in `evaluate_offer`
- `backend/routes/chat.py` — drains `pending_discount` in the SSE stream loop, emits `data-discount`
- `backend/tests/test_routes_chat.py` — Scenarios 1–3
- `backend/tests/test_agent_tools_negotiation.py` — unit coverage of `evaluate_offer`'s own Redis write + `pending_discount` write (ACCEPT, COUNTER, no-commit, and no-`user_id` paths)

**Frontend**
- `frontend/app/stores/item.ts` — `useItemStore` (new file; `useState`-backed, see above)
- `frontend/app/pages/chat.vue` — `fetchIfMissing` on mount instead of a per-turn refetch; `useChat`'s top-level `onData` option calls `applyDiscount`
- `frontend/app/components/ItemCard.vue` — reads the store if an entry exists (overlaying its live `discountedPrice`), falls back to the `item` prop's own `discounted_price` otherwise
- `frontend/app/pages/items/[id].vue` — fetches via `fetchIfMissing`/renders from live store state; the 409 retry path uses `refetch`
- `frontend/tests/stores/item.test.ts` — Scenarios 4–6, plus `refetch`
- `frontend/tests/pages/chat.test.ts`, `frontend/tests/components/ItemCard.test.ts`, `frontend/tests/pages/items/id.test.ts` — component-level wiring coverage
