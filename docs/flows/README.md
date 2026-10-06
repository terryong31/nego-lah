# Core Flows

Sequence diagrams for the journeys that cross the most components. Living document; the
component overview is in [Architecture](../architecture/README.md).

---

## 1. A negotiation turn

```mermaid
sequenceDiagram
    autonumber
    actor Buyer
    participant SPA as Nuxt SPA
    participant API as FastAPI
    participant Redis
    participant Agent as Agent (bot.py)
    participant LLM as Qwen (M5) or Gemini

    Buyer->>SPA: "RM280 can bro?"
    SPA->>API: POST /chat/stream (cookie + X-CSRF-Token)
    API->>API: Persist the buyer message, start a detached turn
    API->>Redis: Probe local model, take lease llm:qwen:busy (NX, 45 s)
    Redis-->>API: Granted → Qwen, held → Gemini
    API->>Agent: Run the turn on the pinned provider
    Agent->>API: evaluate_offer(280)
    API-->>Agent: COUNTER RM300 (floor never returned)
    Agent->>LLM: Phrase the reply
    LLM-->>API: Tokens
    API-->>SPA: SSE chunks
    API->>Redis: Release lease; publish to the buyer's channel
    SPA-->>Buyer: Reply bubble
```

On the local model the agent step is split into a decider and a speaker; see
[agent architecture](../architecture/agent.md#2-running-the-turn-botpy).

---

## 2. Optimistic Claim-at-Payment & Fulfillment Flow (ADR-0001)

Nego-Lah deliberately avoids pessimistic inventory locking to prevent denial-of-inventory attacks and cart hoarding. Items stay available until paid; concurrency is resolved atomically at fulfillment:

```mermaid
sequenceDiagram
    autonumber
    actor Buyer
    participant SPA as Nuxt SPA
    participant API as FastAPI
    participant Stripe as Stripe API
    participant DB as Supabase PostgreSQL
    actor Seller as Seller / Resend

    Note over Buyer,DB: Phase 1: Checkout Session Creation (Item stays available)
    Buyer->>SPA: Clicks "Buy Now" / "Pay RM280"
    SPA->>API: POST /payment/checkout
    API->>DB: SELECT status FROM items WHERE id = item_id
    alt Item already sold
        API-->>SPA: 409 Conflict ("Item is no longer available")
    else Item available
        API->>Stripe: Create Checkout Session (negotiated price + pre-filled email)
        Stripe-->>API: checkout_url
        API-->>SPA: { checkout_url }
        SPA->>Buyer: Redirect to Stripe Hosted Checkout
    end

    Note over Buyer,DB: Phase 2: Payment & Atomic Claim (Fulfillment)
    Buyer->>Stripe: Completes payment on Stripe
    Stripe->>API: POST /payment/webhook/stripe (checkout.session.completed or payment_link.completed)
    API->>DB: INSERT INTO orders (stripe_payment_id) [UNIQUE idempotency anchor]
    
    API->>DB: UPDATE items SET status='sold', buyer_id=user_id WHERE id=item_id AND status='available'
    alt Claim Succeeded (Winner - rows updated = 1)
        API->>DB: INSERT INTO transactions (status='completed')
        API->>SPA: Broadcast thank-you & shipping address request
        API->>Seller: Dispatch purchase receipt (Buyer) & sale alert (Seller) via Resend
    else Claim Failed (Lost Concurrent Race - rows updated = 0)
        API->>Stripe: Auto-refund loser: stripe.Refund.create(payment_intent)
        API->>DB: UPDATE orders SET status='refunded'
        API->>SPA: Broadcast apology & refund notice ("Item was bought moments before your payment")
    end
```

---

## 3. Human-in-the-Loop (HITL) Takeover Flow

```mermaid
sequenceDiagram
    autonumber
    actor Buyer
    participant API as FastAPI
    participant DB as Supabase
    actor Seller as Human Seller (Admin Console)

    Buyer->>API: "Can we COD at Mid Valley?"
    API->>API: Agent calls transfer_to_human (COD policy)
    API->>DB: UPDATE chat_settings SET ai_enabled=false, admin_intervening=true
    API-->>Buyer: "I'll pass you to Terry to arrange COD!"
    Seller->>API: POST /admin/chats/{user_id}/message
    API->>DB: INSERT INTO messages (source='admin', content='...')
    API-->>Buyer: SSE on /chat/notifications/stream
```
