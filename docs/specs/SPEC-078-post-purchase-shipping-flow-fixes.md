---
id: SPEC-078
title: Post-Purchase Shipping Flow Fixes
status: complete
priority: high
created: 2026-09-14
tags: [agent, chat, sse, shipping, orders]
assigned: agent
---

# Context & Objectives
Three bugs in the post-purchase shipping flow, reported together:
1. While the Stripe sub-agent is saving the buyer's shipping details, the SSE
   status bubble still reads "Generating payment link..." — the wrapper tool
   `call_stripe_agent` fronts three jobs (create link, cancel, collect
   shipping info) but the top-level stream hardcoded one label for all three.
2. `collect_shipping_info` required name + phone + address in a single call.
   A buyer who gives only their name got nothing saved and the same "please
   provide all three" prompt repeated, instead of the name being kept and
   only the rest being asked for.
3. Admin "record shipment" (notify buyer) reports success and the email
   lands, but the chat message the buyer is supposed to see never actually
   appears in their conversation — `_notify_buyer_of_shipment` only pushed a
   live Realtime/SSE broadcast and never wrote a `messages` row, so a buyer
   who wasn't on the chat page at that exact instant lost the notice for
   good.

# Acceptance Criteria
- [x] SSE status for `call_stripe_agent` is derived from what it is actually
      asked to do (its `request` argument), not hardcoded to the payment-link
      case: shipping-related requests show a shipping status, cancellations
      show a cancel status, everything else falls back to the payment-link
      status.
- [x] `collect_shipping_info` accepts any subset of `recipient_name`/`phone`/
      `address`, saves only the field(s) given, merges with whatever was
      saved in earlier turns, and only flips the order to `confirmed` once
      the merged set is complete. The reply says what was saved and what's
      still missing.
- [x] `_notify_buyer_of_shipment` (admin shipment record + delivered status)
      persists the notice to `messages` before the live broadcast, so it is
      in the buyer's history whether or not they were online at the moment
      it was sent.

# Technical Design & Contracts
- `backend/agent/bot.py::chat_stream` — `call_stripe_agent`'s tool-call
  arguments stream in as raw JSON text across multiple `tool_call_chunks`
  (keyed by tool-call id). They are buffered per id and only classified once
  `json.loads` on the accumulated text succeeds; `_classify_stripe_request`
  keyword-matches the `request` string ("cancel" → cancel status; "ship" /
  "address" / "phone" / "recipient" / "deliver" → shipping status; else →
  payment-link status). Every other tool keeps its existing immediate,
  name-only status lookup.
- `backend/agent/tools/payment.py::collect_shipping_info` — signature changes
  to `(order_id, recipient_name=None, phone=None, address=None)`. Reads the
  order's current `recipient_name`/`phone`/`address` first (ownership-scoped
  SELECT, same fail-closed `user_id` gate as before), merges with whatever
  was passed this call, writes only the field(s) passed this call (never
  blanks unset columns), and sets `status='confirmed'` only when the merged
  set is complete.
- `backend/routes/admin/orders.py::_notify_buyer_of_shipment` — calls
  `conversation_memory.add_message(buyer_id, "ai", message, item_id=...,
  source="ai")` immediately before `broadcast_to_chat`, inside the same
  best-effort `try`, mirroring the existing `_send_thank_you` pattern in
  `payment/fulfillment.py`.

# Test-Driven Development (TDD) Scenarios
- [x] `call_stripe_agent` with a shipping-flavored `request` (split across
      several arg chunks) yields exactly one `{"status": "Saving your
      shipping details..."}`, once the JSON is complete.
- [x] A cancel-flavored request yields the cancel status; an empty/ambiguous
      `request` falls back to the payment-link status.
- [x] `collect_shipping_info` given only a name: writes `{"recipient_name":
      ...}` only, does not touch `status`, and the reply asks for phone and
      address.
- [x] `collect_shipping_info` given the last missing field: merges with the
      order's existing (previously-saved) fields, writes the new field plus
      `status: confirmed`.
- [x] `_notify_buyer_of_shipment` (both the shipment-recorded and the
      delivered path) calls `conversation_memory.add_message` even when the
      subsequent broadcast fails.

# Implementation Files
- `backend/agent/bot.py` - buffered, classified SSE status for `call_stripe_agent`
- `backend/agent/tools/payment.py` - partial/merged `collect_shipping_info`
- `backend/agent/sub_agents/stripe_agent.py` - prompt instructs saving partial info immediately
- `backend/routes/admin/orders.py` - persist shipment/delivery chat notice before broadcasting
- `backend/tests/test_agent_bot.py`, `test_agent_tools_payment.py`, `test_routes_admin_shipment.py` - updated/new coverage
