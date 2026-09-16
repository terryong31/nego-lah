# Core System Flows & State Machines

This directory documents the key end-to-end user journeys and state machine workflows across Nego-Lah.

---

## 1. Real-Time AI Bargaining & Streaming Flow

```mermaid
sequenceDiagram
    autonumber
    actor Buyer
    participant SPA as Nuxt 4 SPA (Cloudflare Pages)
    participant API as FastAPI (:8000)
    participant Redis as Redis 7
    participant Agent as LangGraph Supervisor
    participant LLM as Hybrid LLM (Qwen / Gemini)

    Buyer->>SPA: Types offer ("RM280 can bro?")
    SPA->>API: POST /chat/{item_id}
    API->>Redis: Acquire token-owned lease (10s TTL)
    Redis-->>API: Lease granted
    API->>Agent: Invoke LangGraph state graph
    Agent->>API: Call evaluate_offer(item_id, 280)
    API-->>Agent: Floor check pass (min_price protected)
    Agent->>LLM: Stream counter-offer / acceptance
    LLM-->>API: Token chunks
    API-->>SPA: SSE Event: text_chunk
    SPA-->>Buyer: Live typing animation & bubble update
```

---

## 2. Optimistic Claim-at-Payment & Fulfillment Flow (ADR-0001)

Nego-Lah deliberately avoids pessimistic inventory locking to prevent denial-of-inventory attacks and cart hoarding. Items stay available until paid; concurrency is resolved atomically at fulfillment:

```mermaid
sequenceDiagram
    autonumber
    actor Buyer
    participant SPA as Nuxt 4 SPA
    participant API as FastAPI (:8000)
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
    Stripe->>API: Webhook: checkout.session.completed
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
    API->>API: Tool handoff_to_human triggered (COD policy)
    API->>DB: UPDATE chat_settings SET ai_enabled=false, admin_intervening=true
    API-->>Buyer: "I'll pass you to Terry to arrange COD!"
    Seller->>API: POST /admin/chats/{user_id}/message
    API->>DB: INSERT INTO messages (source='admin', content='...')
    API-->>Buyer: SSE notification: seller active in chat
```
