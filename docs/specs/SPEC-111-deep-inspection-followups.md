---
id: SPEC-111
title: Re-Sold Items Refund, Dead Sub-Agents Go, Errors Stop Leaking
status: complete
priority: medium
created: 2026-10-27
tags: [billing, agent, security, cache, cleanup]
assigned: agent
---

# Context & Objectives

A deep-inspection review raised seven points. Each was checked against the code and all of them held:

- **Re-sold items cannot be refunded.** `process_refund` read `transactions` by `item_id` with no
  order and took `data[0]`. After a refund and a re-sale that row could be the refunded one, so the
  second buyer's refund was refused as "already refunded". The update that followed matched by
  `item_id`, so it marked every sale of the item as refunded.
- **Dead sub-agents.** SPEC-079 bound the domain tools directly, but `bot.py` still imported
  `item_agent`/`stripe_agent`, which compiled two LangGraph graphs at import. It also kept the
  `call_item_agent`/`call_stripe_agent` wrappers and a streaming parser for a tool that is never bound.
- **Stale Realtime comments.** `ConversationMemory.broadcast_message` is a no-op that has no callers
  and claims Supabase Realtime still delivers messages. `chat.vue`, `AdminChats.vue` and
  `billing/admin_routes.py` describe a transport that SPEC-094 removed.
- **Exception text in 500s.** `/payment/checkout` and `/payment/active/{id}` put `str(e)` in the
  response.
- **Unescaped inbound-mail text.** The forwarder wrapped a text-only email in `<pre>` without escaping
  it, so the email's text was rendered as HTML.
- **Cache fingerprint blind to edits.** `get_items_fingerprint` hashed `COUNT` and `MAX(created_at)`,
  so an edit made in Supabase Studio stayed in the storefront cache for up to an hour.

# Acceptance Criteria

- [x] A refund picks the newest transaction for the item that is not yet refunded, and marks only
      that payment (`stripe_payment_id`) refunded. An item that was refunded and re-sold can be
      refunded again.
- [x] `sub_agents/`, both wrapper tools, `_classify_stripe_request` and the `call_stripe_agent` arg
      buffering are deleted. A tool call yields its status as soon as its name arrives.
- [x] `broadcast_message` is deleted. The three stale comments describe SSE.
- [x] Both payment routes return a fixed 500 message and log the exception server-side.
- [x] The plain-text fallback is `html.escape`d.
- [x] `items.updated_at` is set by a trigger on every update and granted to the storefront roles.
      The fingerprint is `COUNT` + `MAX(updated_at)`, read before the data on a cache miss.

# Technical Design & Contracts

- Migration `20261027000000_items_updated_at.sql`: adds the column with default `now()`, backfills
  it from `created_at`, adds a `before update` trigger, and grants `select (updated_at)` to
  `anon` and `authenticated`. `min_price` and `buyer_id` stay ungranted.
- On a cache miss the fingerprint is read before the rows. If an edit lands in between, the stored
  hash is older than the data, and the next check refetches. The reverse order could freeze stale
  rows behind a current hash.

# TDD Scenarios

- Rows `[completed(pi_2), refunded(pi_1)]` refund `pi_2` and update by `stripe_payment_id`.
  `[refunded]` alone is still refused.
- `bot` has no `call_item_agent`, `call_stripe_agent` or `item_agent` attribute, and a
  `create_checkout_link` chunk yields its status at once.
- The checkout and active-payments 500s do not contain the exception text.
- A text body `<script>` is forwarded as `&lt;script&gt;`.
- The fingerprint orders by `updated_at`. A cache miss stores the fingerprint's hash.
- The migration grants `updated_at`, creates the trigger, and grants no `min_price`.

# Implementation Files

- `backend/domains/billing/{refunds,routes,admin_routes}.py`, `backend/domains/webhooks/routes.py`
- `backend/domains/negotiation/{bot,memory}.py`, `backend/domains/negotiation/sub_agents/` (deleted)
- `backend/domains/catalog/items.py`, `supabase/migrations/20261027000000_items_updated_at.sql`
- `frontend/app/pages/chat.vue`, `frontend/app/components/admin/AdminChats.vue`
