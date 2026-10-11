---
id: SPEC-105
title: One Floor-Price Resolver, Fail-Closed When the Seller Sets None
status: complete
priority: high
created: 2026-10-11
tags: [catalog, negotiation, billing, pricing]
assigned: agent
---

# Context & Objectives

`min_price` is optional: the admin form sends `None` when the seller leaves it blank, and the
column is nullable. Three call sites resolved the floor three ways:

| Site | Expression | Unset floor became |
|---|---|---|
| `evaluate_offer` | `float(item.get("min_price", listed * 0.7))` | **TypeError** — the row always carries the key, so the default never fired and `float(None)` raised |
| `create_checkout_link` | `float(item.get("min_price") or item.get("price", 0))` | the listed price |
| `POST /checkout` (Buy Now) | `float(item.get("min_price") or listed_price)` | the listed price |

So an item listed without a floor crashed every price turn, and the 70 % default the negotiation
tests asserted was only reachable from a test fixture that omitted the key. Had it been reachable,
the agent would have conceded to 70 % and checkout would then have refused that price.

The fix is one resolver, and it fails closed: a seller who set no floor authorised no discount.

# Acceptance Criteria

- [x] `CatalogService.floor_price(item)` is the only place a floor is derived from an item row.
- [x] An unset (`None`, missing, or non-positive) floor resolves to the listed price.
- [x] A floor above the listed price is clamped to the listed price.
- [x] `evaluate_offer`, `create_checkout_link` and `POST /checkout` all call it.
- [x] `evaluate_offer` on an item with `min_price = None` returns a result instead of raising, and concedes nothing below the listing.

# Technical Design & Contracts

`CatalogService.floor_price(item: dict) -> float` — pure, no I/O. Catalog owns the `items` row, so
it owns its interpretation; negotiation and billing sit above catalog and import it through the
package (ADR-0030).

# TDD Scenarios

- [x] `floor_price` returns the set floor; the listed price for `None`, missing, `0`; the listed price for a floor above it.
- [x] `evaluate_offer` with `min_price: None` and an offer under the listing → `REJECT_FLOOR`, no exception.
- [x] `create_checkout_link` with `min_price: None` refuses a price under the listing.

# Implementation Files

- `backend/domains/catalog/services.py` — `floor_price`
- `backend/domains/negotiation/tools/negotiation.py`, `backend/domains/negotiation/tools/payment.py`, `backend/domains/billing/routes.py` — call it
- `backend/tests/test_floor_price_resolver.py`, `backend/tests/test_agent_tools_negotiation.py`
