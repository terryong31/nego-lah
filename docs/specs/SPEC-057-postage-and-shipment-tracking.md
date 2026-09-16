---
id: SPEC-057
title: Postage & Shipment Tracking - Admin Upload, Buyer Notification, Agent Awareness
status: complete
priority: high
created: 2026-09-09
tags: [orders, shipping, email, agent, admin]
assigned: agent
---

# Context & Objectives

The order lifecycle stops at `confirmed`. A buyer who has paid and sent their address has
no way to learn anything after that: `orders.status` can be flipped to `shipped`, but there
is nowhere to record *what was shipped with* or *under what tracking number*, so the status
alone tells them nothing they can act on. The seller ends up pasting tracking numbers into
the chat by hand, and the agent — asked "where's my stuff?" — can only report a word.

This closes the loop (TODO 49 + 50): the seller records postage once, and that single act
notifies the buyer three ways.

**Non-goal:** courier API integration. Nothing polls a carrier. The seller is the source of
truth, which is correct for a single-seller store shipping a handful of parcels a week.

# Acceptance Criteria

- [x] **Schema.** `orders` gains `courier`, `tracking_number`, `tracking_url`, `shipped_at`,
      `delivered_at`. Additive and nullable — existing rows are untouched and every path
      keeps working when they are NULL.
- [x] **Admin records postage.** `PUT {ADMIN_PREFIX}/orders/{order_id}/shipment` takes
      `{courier, tracking_number, tracking_url?, notify?}`. It stamps `shipped_at`, moves
      the order to `shipped`, and writes an audit entry. CSRF-protected by living on the
      `protected` router (SPEC-056 #1).
- [x] **Tracking URL is derived, not typed.** A courier registry maps the Malaysian carriers
      this store actually uses to a URL template; an explicit `tracking_url` overrides it,
      and an unknown courier simply yields none rather than failing.
- [x] **Buyer is told, three ways.** One `PUT` sends the shipment email, posts a chat message
      the buyer sees live, and rings the SSE notification bell. `notify: false` opts out for
      a correction to an already-announced shipment.
- [x] **Delivery is a transition too.** Moving an order to `delivered` stamps `delivered_at`
      and notifies once; moving it back out does not re-notify.
- [x] **Notification failure never loses the record.** Email/broadcast run after the write
      and are individually best-effort; the response reports what actually went out.
- [x] **Agent knows.** `check_user_orders` reports courier, tracking number and tracking URL
      for shipped orders. **No new tool** — a tool costs a schema in every prompt of every
      turn, and this is the same question `check_user_orders` already answers (see SPEC-058).
- [x] **Console UI.** The orders table's expanded row gains a postage form: courier select,
      tracking number, optional URL, notify toggle. Shipped orders show what was recorded.
- [x] **Trilingual.** Every new string in `en` / `ms` / `zh`.

# Technical Design & Contracts

```
PUT {ADMIN_PREFIX}/orders/{order_id}/shipment
  body  {courier: str, tracking_number: str, tracking_url?: str, notify?: bool = true}
  200   {message, order, notified: {email: bool, chat: bool}}
  400   blank courier / tracking number
  404   unknown order
```

`domains/catalog/shipping.py` — the courier registry, one dict:
```python
COURIERS = {"jt": ("J&T Express", "https://www.jtexpress.my/tracking?billcode={tracking}"), ...}
resolve_tracking_url(courier, tracking_number) -> str | None
```

Buyer-facing copy is generated in one place, `services/shipping_notice.py`, so the email,
the chat bubble and the agent's answer cannot drift apart.

# Test-Driven Development (TDD) Scenarios

- [x] **S1:** `PUT .../shipment` writes courier/tracking/`shipped_at`, sets status `shipped`, audits.
- [x] **S2:** without a CSRF header → 403 and nothing written.
- [x] **S3:** blank courier or tracking number → 400, no write.
- [x] **S4:** a known courier derives a tracking URL; an explicit one wins; an unknown one gives None.
- [x] **S5:** a successful write sends one email and one chat broadcast; `notify: false` sends neither.
- [x] **S6:** a failing email still returns 200 with the order written and `notified.email == false`.
- [x] **S7:** status → `delivered` stamps `delivered_at` and notifies; `delivered` → `shipped` does not.
- [x] **S8:** `check_user_orders` renders courier + tracking for a shipped order, and is unchanged for orders without it.
- [x] **S9:** the shipment email renders courier, tracking number and a track button.

# Implementation Files

- `supabase/migrations/20260910000000_order_shipment_tracking.sql`
- `backend/domains/catalog/shipping.py` — courier registry + URL resolution
- `backend/services/shipping_notice.py` — one source of buyer-facing shipment copy
- `backend/services/email_service.py` — `send_shipment_notice`
- `backend/templates/emails/shipment_notice.html`
- `backend/routes/admin/orders.py` — the shipment endpoint + delivered transition
- `backend/schemas.py` — `ShipmentUpdate`
- `backend/agent/tools/orders.py` — tracking in `check_user_orders`
- `frontend/app/components/admin/AdminOrders.vue` — postage form
- `frontend/app/locales/{en,ms,zh}.json`
- `docs/adr/0019-seller-reported-shipment-tracking.md`
