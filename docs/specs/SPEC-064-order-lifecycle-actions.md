---
id: SPEC-064
title: Order Row Actions and the Shipment Modal
status: complete
priority: high
created: 2026-09-10
tags: [admin, orders, frontend, shipping, ux]
assigned: agent
---

# Context & Objectives

An order row states its status three times: a `UBadge` in the Status column, a
`USelect` in the actions cell that shows the same word, and — once expanded —
a "Shipped on …" line. The `USelect` is the worst of the three: it is 144px of
the widest column spent restating a value the row already shows, and it makes
the seller's most common action (posting a parcel) look like a dropdown choice
rather than a thing you do.

The thing you actually do is buried. Postage is a four-field form inside the
expanded row, so recording a shipment means noticing there is a chevron,
expanding, scrolling past the shipping address, and filling in a form that
shares a cramped grid column. Nothing on the collapsed row says whether an order
still needs posting.

Correcting a mistake is worse: the form is only reachable by expanding, and
re-submitting re-stamps `shipped_at` to now, so fixing a typo in a tracking
number silently moves the ship date.

# Acceptance Criteria

- [x] The status `USelect` is gone from the actions cell.
- [x] A `confirmed` order shows a **Ship** link button; clicking it opens a
      modal with the postage form.
- [x] A `shipped` or `delivered` order shows an **Edit shipment** link button
      opening the same modal, prefilled with what was recorded.
- [x] Submitting records the shipment, flips the status to `shipped`, emails
      the buyer and posts the agent's message in their chat — one submit, as
      today.
- [x] Re-recording a shipment keeps the original `shipped_at`. Correcting a
      typo must not move the ship date.
- [x] "Notify the buyer" defaults ON for a first record and OFF for an edit;
      the seller can always override.
- [x] Every other status transition (confirm, mark delivered, cancel, refund)
      survives, in an overflow menu with Delete — removing the select must not
      remove the capability.
- [x] The expanded row keeps the buyer's shipping address and now shows the
      recorded tracking read-only, with a "Track parcel" link when there is one.
- [x] The modal validates courier + tracking number before it will submit.
- [x] The tracking-link footnote is a `150ms` tooltip on an info icon at the end
      of its label row, not a line of body text pushing the input down. Its
      trigger is a real button, so the hint is reachable without a pointer.

# Technical Design & Contracts

**Backend** — one change. `PUT /admin/orders/{id}/shipment` stamps
`shipped_at` only when the order does not already have one; a re-record updates
courier / tracking / URL and leaves the original date alone. `notify` already
exists for corrections and is unchanged.

**Frontend** `AdminOrders.vue`:

- `shipping` ref holds `{ order, draft }`; one `UModal` is rendered once,
  outside the table, driven by it.
- `rowActions(order)` returns `DropdownMenuItem[][]`: the status transitions
  valid from where the order is, then Delete.
- The actions cell becomes: contextual link button + `i-lucide-ellipsis-vertical`
  menu. No select.
- The postage form moves wholesale from `#expanded` into the modal; the
  expanded row keeps the address and gains a read-only tracking summary.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1 (api):** Re-recording a shipment preserves the original
      `shipped_at` and still updates courier/tracking. Fails pre-fix.
- [x] **Scenario 2 (api):** A first record still stamps `shipped_at`.
- [x] **Scenario 3:** A confirmed row renders **Ship** and no `USelect`.
- [x] **Scenario 4:** A shipped row renders **Edit shipment**, and opening it
      prefills courier / tracking / URL.
- [x] **Scenario 5:** Submitting posts to `/orders/{id}/shipment`, flips the
      row to `shipped`, and closes the modal.
- [x] **Scenario 6:** Notify defaults true for an unshipped order, false for an
      already-shipped one.
- [x] **Scenario 7:** Submitting with a blank courier or tracking number warns
      and sends nothing.
- [x] **Scenario 8:** The overflow menu still changes status and deletes.

# Implementation Files

- `backend/routes/admin/orders.py` - `shipped_at` preserved on re-record
- `backend/tests/test_routes_admin_shipment.py` - re-record coverage
- `frontend/app/components/admin/AdminOrders.vue`
- `frontend/app/locales/{en,ms,zh}.json`
- `frontend/tests/components/admin/AdminOrdersShipment.test.ts` - new coverage.
  Mounts inside `UApp`: `UTooltip` reads a provider context that `UApp`
  installs and `app.vue` wraps the whole application in one, so mounting the
  component bare is the unrealistic part, not the tooltip.
- `frontend/tests/components/admin/AdminOrders.test.ts` - the select/trash tests
  restated against the overflow menu, and the postage block given the
  `clearNuxtData` reset it never inherited from its sibling describe (it shares
  one `useAsyncData('admin-orders')` with every mount in the file, and
  `recordShipment` mutates the order in place, so one test's shipped order was
  becoming the next test's starting state)
