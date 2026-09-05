---
id: SPEC-031
title: Item card padding parity and sold-item treatment
status: complete
priority: medium
created: 2026-09-06
tags: [frontend, ui, catalog]
assigned: agent
---

# Context & Objectives

Three defects in `components/ItemCard.vue`, all visible on the storefront grid.

1. **The image, the title/condition block and the price row sit at three
   different horizontal insets.** The card body is `p-0`, so the image is
   full-bleed while the text below it is inset by the inner wrapper's
   `p-2.5 sm:p-3` and the footer by its own. The card's *own loading skeleton*
   already settles the intended design: it puts `p-2.5 sm:p-3` on the whole card
   and renders a `rounded-lg` image inside it. The loaded card contradicts its
   skeleton, so the grid visibly reflows when data arrives.

2. **A sold item's photo looks identical to an available one.** Nothing but a
   small badge distinguishes them, so a sold-out grid reads as shoppable.

3. **The "Sold" badge is too small** to register at grid density.

# Acceptance Criteria

- [x] The image, the title/condition block and the price row share one
      horizontal inset at every breakpoint.
- [x] The loaded card matches its own skeleton: padded card, inset image with
      `rounded-lg` corners — no reflow between loading and loaded.
- [x] A sold item's image is rendered greyed out; an available item's is not.
- [x] The "Sold" badge is visibly larger than the previous `sm`.
- [x] Nothing about pricing, translation, navigation or image-URL resolution
      changes (the existing suite stays green).

# Technical Design & Contracts

Padding moves from the inner text wrapper up to the card's `body` slot, so the
`body` and `footer` slots carry the same `p-2.5 sm:p-3` and every child inherits
one inset. The image gains `rounded-lg` to match the skeleton.

`isSold` (a computed on `item.status === 'sold'`) drives both the greyscale
treatment on the `<img>` and the badge, replacing the inline status check.

No API, schema or prop changes — this is presentation only, so no ADR: it is not
an architectural decision.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** The `body` and `footer` slot classes carry identical
      padding utilities.
- [x] **Scenario 2:** The text wrapper no longer sets its own padding, so it
      cannot drift from the image's inset.
- [x] **Scenario 3:** The image wrapper is `rounded-lg`, matching the skeleton.
- [x] **Scenario 4:** A `sold` item's `<img>` carries the greyscale treatment.
- [x] **Scenario 5:** An `available` item's `<img>` does not.
- [x] **Scenario 6:** The "Sold" badge renders at a size larger than `sm`.

# Implementation Files

- `frontend/app/components/ItemCard.vue` - padding parity, `isSold`, badge size
- `frontend/tests/components/ItemCard.test.ts` - scenarios above
