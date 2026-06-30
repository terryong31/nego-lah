# 1. Optimistic claim-at-payment over pessimistic inventory locking

- Status: Accepted
- Date: 2026-06-30
- Deciders: Terry (owner)

## Context

Nego-Lah sells **personal, one-of-a-kind items (quantity = 1)**. Two payment
entry points exist, and both ultimately charge the buyer through Stripe:

1. **AI chat negotiation** — the agent negotiates a price and calls
   `create_checkout_link`, which creates a Stripe **PaymentLink** (valid ~3
   days) and stores pending state in Redis keyed by `(user_id, item_id)`.
2. **Item-page "Buy" button** — `POST /payment/checkout` creates a Stripe
   **Checkout Session** at the listed price.

The core risk for quantity-1 inventory is **selling the same item twice**: two
buyers paying at (nearly) the same time. We needed to decide how to prevent
double-sells without creating worse problems.

A common recommendation for this scenario is **pessimistic inventory locking**
(Approach 1): when a buyer starts checkout, mark the item `pending_payment`
with a TTL and block everyone else until they pay or the lock expires. We
evaluated this seriously before deciding.

### Decision drivers

- Must never charge two buyers for the same 1-of-1 item without an automatic,
  no-manual-work resolution.
- Low transaction volume; genuinely simultaneous payments are rare.
- The AI flow has **no clean "checkout moment"** and uses a **long-lived
  (3-day) PaymentLink**, which is fundamentally incompatible with a short
  inventory lock (the lock would expire long before the link does).
- The store is fronted by an AI that hands out payment links freely, making
  **denial-of-inventory** trivial: anyone can negotiate, obtain a link, and
  never pay — locking the single item for the whole TTL.
- Two entry points with **opposite locking ergonomics** (Checkout Sessions have
  a native `expires_at`; PaymentLinks do not), so a uniform pessimistic lock
  would require two different reservation/expiry mechanisms kept in sync.

## Considered options

1. **Pessimistic inventory lock** — reserve the item on checkout start, block
   others, release via TTL/cron. Classic, strong UX guarantee for the buyer who
   committed.
2. **Optimistic claim-at-payment** — items stay available until payment
   succeeds; the item is claimed atomically at fulfillment, and any losing
   concurrent payment is automatically refunded.
3. **Optimistic core + soft "Sale pending" reserve** — option 2 plus a
   cosmetic, self-expiring reservation badge.

## Decision

Adopt **Approach 2: optimistic concurrency with an atomic claim at the moment
of payment**, enforced in a single, path-agnostic fulfillment step shared by
both entry points. Do **not** implement pessimistic inventory locking.

Concretely:

- **Single source of truth at fulfillment.** Both the webhook and the frontend
  `confirm-payment` fallback funnel through `fulfill_purchase`
  (`backend/payment/fulfillment.py`), which:
  - **Idempotency gate** — inserts the order keyed on the Stripe PaymentIntent
    id (`orders.stripe_payment_id`, `UNIQUE`). The first writer wins; retries
    and duplicate paths no-op. (See migration
    `supabase/migrations/20260630000000_payment_idempotency.sql`.)
  - **Atomic claim** — `UPDATE items SET status='sold' WHERE id=? AND
    status='available'`. Exactly one concurrent payment can win.
  - **Auto-refund the loser** — if the claim fails, the just-charged payment is
    refunded via Stripe and the buyer is notified. No manual intervention.
- **Cheap availability guard at each entry point** — both `create_checkout_link`
  and `POST /payment/checkout` reject if the item is not `available` (the Buy
  button returns `409`). This is a UX nicety; the atomic claim remains the
  authority if two buyers race past the guard.
- **Trust the webhook, not the redirect**, and trust Stripe's `amount_total`
  for the recorded amount.

A soft, self-expiring "Sale pending" reservation (Option 3) is permitted as
**future cosmetic polish only**, layered on top of the atomic claim — never as
the mechanism that guarantees correctness.

## Consequences

### Positive

- One mechanism protects every entry point; new payment paths inherit
  correctness for free.
- No denial-of-inventory: items are never held hostage by abandoned carts,
  bots, or tire-kicking AI negotiations.
- No items stuck in a `pending` limbo requiring a reliable release worker.
- Double-sells resolve automatically (atomic claim + auto-refund); idempotency
  prevents duplicate orders from webhook retries.

### Negative / trade-offs

- A buyer can, in the rare simultaneous case, complete payment and then be
  refunded with a "sold to someone else" message — a worse moment than being
  blocked up front. Accepted given the low probability at this volume.
- Auto-refunds may incur Stripe fees that are not always returned. Negligible at
  expected collision frequency.
- The auto-refund path means the system issues refunds for lost races even
  though refunds are otherwise manual/admin-only. This is a deliberate safety
  exception (the system caused the double charge).

### Follow-ups (not blocking this decision)

- Schedule `cleanup_expired_payments()` (currently only a manual admin action)
  so abandoned 3-day PaymentLinks are cleaned up automatically.
- Handle item-page `409` ("no longer available") gracefully in the frontend.
- Optionally listen for `charge.refunded` / `charge.dispute.created` to keep
  item status in sync with dashboard-initiated refunds.
