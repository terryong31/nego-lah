---
id: SPEC-016
title: Negotiated Price, Checkout Hand-off and Outcome UX, and Stripe SDK v15 Compatibility
status: complete
priority: high
created: 2026-09-05
tags: [frontend, backend, payment, stripe, chat, i18n, ui]
assigned: agent
---

# Context & Objectives
1. **Stale price in the chat header (frontend):** `/items/{id}` already returns `discounted_price` for the authenticated buyer (derived from the cached negotiated offer), but `pages/chat.vue` rendered the raw listed price and fetched the item exactly once on mount. A buyer who haggled RM1199 down to RM1000 still saw RM1199 above the thread.
2. **Checkout hand-off card (frontend):** the agent's markdown pay link rendered as a blue Stripe-logo tile with the agent's raw label ("Pay RM1000 Now") on the button — off-brand, untranslated, and duplicated verbatim in `pages/chat.vue` and `components/admin/AdminChats.vue`.
3. **Checkout outcome page (frontend):** `checkout/success.vue` rendered four states out of a plain `UCard` with a bare lucide glyph, an invalid `text-danger` class (so the error mark rendered uncoloured), a raw fetch error as body copy, hardcoded English inside an otherwise trilingual app, and two competing buttons on the success state.
4. **Checkout confirmation is broken in production (backend):** stripe-python 15.x removed the dict methods from `StripeObject` (`.get()` now raises `AttributeError: 'get' is a dict method…`). `routes/payment.py::confirm_payment` and `payment/webhooks.py::handle_checkout_completed` both read Stripe resources with `.get()`, so **every** paid checkout 500s — both the webhook fulfilment path and the success-page fallback. The 500 carries no CORS headers, so the browser reports only `<no response> Failed to fetch`. Existing tests passed because their fixtures were `MagicMock`s and plain dicts, which support `.get()`.

# Acceptance Criteria
- [x] Chat header shows the negotiated price, the struck-through listed price, and the discount percentage.
- [x] Chat header pins the listing in the reader's language (falling back to the seller's wording) with translated Buy / Sold labels.
- [x] Chat header refetches the context item when an agent turn finishes streaming (never mid-stream).
- [x] Item detail page shows a `-N%` badge (`size="md"`) in place of the hardcoded "Special Offer".
- [x] One shared `ChatPayCard` renders the hand-off in both the customer chat and the admin console; the agreed amount is the headline, Stripe is a trust footnote carrying the official wordmark.
- [x] Checkout outcome page: one illustrated Memphis scene per state, exactly one filled button per view, secondary action `ghost` (never `outline`), no storefront button on success, order reference shown as a receipt stub, all copy translated (en/ms/zh).
- [x] Reading a field off a Stripe resource never raises `AttributeError`; `confirm_payment` and `handle_checkout_completed` work against real `StripeObject`s.
- [x] Backend tests exercise real `stripe.checkout.Session` objects, not dicts/`MagicMock`s, so an SDK-shape regression fails the suite.

# Technical Design & Contracts
### `frontend/app/utils/pricing.ts` (auto-imported)
`hasDiscount(item)`, `effectivePrice(item)`, `discountPercent(item)`, `formatPrice(amount)`, `parsePriceFromLabel(label)` — one source of truth for the discount rule, the `RM x.xx` format, and pulling the amount out of the agent's `[Pay RM1000 Now](url)` label.

### `backend/payment/stripe_compat.py`
```python
stripe_get(obj, key, default=None)  # dict | StripeObject | None -> value
```
Uses `obj[key]` (the accessor `StripeObject` still supports) for Stripe resources and `.get()` for mappings. All Stripe-resource field reads in `routes/payment.py` and `payment/webhooks.py` go through it.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** `confirm_payment` against a `stripe.checkout.Session.construct_from({...})` returns `{"status": "success"}` (fails with `AttributeError` before the fix).
- [x] **Scenario 2:** `handle_checkout_completed` with a real `StripeObject` event fulfils, including the PaymentLink metadata fallback.
- [x] **Scenario 3:** `stripe_get` unit tests over dicts, `StripeObject`s, missing keys, and `None`.
- [x] **Scenario 4:** Chat header renders the discounted price + `-17%`, and refetches only after a stream settles.
- [x] **Scenario 5:** `ChatPayCard` headlines the parsed amount and falls back to the raw label when none parses.
- [x] **Scenario 6:** `CheckoutStatusScene` renders the right semantic tint and accent count per variant; the success page shows the order reference, drops the storefront button, and keeps "View My Orders" as `ghost`.

# Implementation Files
- `backend/payment/stripe_compat.py` - SDK-shape-agnostic field reader.
- `backend/routes/payment.py` - `confirm_payment` session/metadata reads.
- `backend/payment/webhooks.py` - `handle_checkout_completed` session/metadata reads.
- `backend/tests/test_payment_stripe_compat.py` - `stripe_get` unit tests.
- `backend/tests/test_routes_payment.py`, `backend/tests/test_payment_webhooks.py` - real `StripeObject` fixtures.
- `frontend/app/utils/pricing.ts` - shared pricing helpers.
- `frontend/app/utils/item.ts` - canonical `ItemTranslation` + `localizedItemField`, shared by the card, detail page and chat pin.
- `frontend/app/components/chat/PayCard.vue` - checkout hand-off card.
- `frontend/app/assets/icons/stripe-wordmark.svg` - official wordmark, `currentColor`.
- `frontend/app/components/checkout/StatusScene.vue` - Memphis outcome illustration (success/refunded/error/pending).
- `frontend/app/pages/checkout/success.vue` - Rebuilt outcome page; localised copy and button hierarchy.
- `frontend/app/pages/chat.vue`, `frontend/app/pages/items/[id].vue`, `frontend/app/components/ItemCard.vue`, `frontend/app/components/admin/AdminChats.vue` - call sites.
