---
id: SPEC-097
title: An Actual Modular Monolith — Acyclic Domains, One Composition Root
status: complete
priority: high
created: 2026-09-20
tags: [backend, architecture, modular-monolith, boundaries, domain-events]
assigned: agent
---

# Context & Objectives
SPEC-092 moved the code into `domains/` and SPEC-095 enforced the import rule backend-wide.
Both pass. Neither asks the question that decides whether this is a modular monolith at all:
**should this dependency exist?**

It does not hold. The four live domains form a **fully connected cyclic graph** — 24 distinct
cycles over 8 back-edges. `catalog ↔ billing`, `catalog ↔ negotiation`, `billing ↔ negotiation`,
`identity ↔ negotiation`. Nothing can be reasoned about, tested or extracted in isolation. The
existing rules pass because they check *how* one domain imports another (package, not module),
never *whether* it should.

Four more structural facts turned up with it:

* **`conversations` has no owner.** `TABLE_OWNER` is only checked against tables some file
  happens to query, so a table in the schema that no code touches is invisible to the rule.
* **`services/` is a fourth layer** — neither a domain nor `core/` — imported by four domains.
* **`core/env.py` loads a `.env` that does not exist.** SPEC-092 moved it from `backend/env.py`
  to `backend/core/env.py` without adjusting `dirname(__file__)`, so it now points at
  `backend/core/.env`. 41 files import it; `core/config.py`, which loads the right file, has 1.
* **`USER_SUPABASE_KEY` resolves two different ways** in those two modules — one falls back to
  `SUPABASE_KEY`, the other fails closed.

Objective: an acyclic domain graph, one composition root, one config module, every table owned —
each enforced mechanically rather than asserted in prose.

# Acceptance Criteria
- [x] **The domain graph is a DAG**, ordered `identity < catalog < billing < negotiation`.
      A domain may only import strictly below itself. Enforced by test, with the rank declared.
- [x] Zero back-edges. The 8 existing ones are removed by **moving code or inverting the
      dependency**, never by re-exporting it from somewhere else.
- [x] `console/` is the single composition root: it may import every domain, and **no domain may
      import it**. `admin_api.py` and `admin_dashboard.py` move there.
- [x] `core/` imports neither a domain nor `console/`.
- [x] `services/` no longer exists; each module is re-homed to the layer that owns it.
- [x] **Every table in `supabase/migrations/` appears in `TABLE_OWNER`** — driven by the schema,
      not by what code happens to query.
- [x] One config module. `core/env.py` loads `backend/.env`; `core/config.py` is deleted; the
      `USER_SUPABASE_KEY` fallback resolves one way.
- [x] Full suite passes, coverage ≥88%, boot cost and route table unchanged.

# Technical Design & Contracts
**Layering.** `RANK = identity 0 · catalog 1 · billing 2 · negotiation 3 · webhooks 4`. An order
needs an item, so billing sits above catalog; the agent needs both, so negotiation sits on top.
Nothing may depend on negotiation.

**`core/bus.py`** — one in-process mechanism so a lower domain never names a higher one:
- `emit(event, **payload)` / `on(event)` — fan-out, no return value. A failing subscriber is
  logged, never raised: a thank-you message must not fail a settled payment.
- `ask(query, default, **payload)` / `provides(query)` — exactly one provider, returns a value.
Subscribers are registered explicitly in `main.py`'s lifespan, because domain `__init__` is lazy
and an unimported subscriber is a silently missing one.

**The 8 back-edges, by remedy:**
| edge | sites | remedy |
|---|---|---|
| billing → negotiation | fulfillment thank-you, shipment chat line | `emit("purchase.fulfilled")`, `emit("shipment.recorded")` |
| identity → negotiation | account deletion purge | `emit("user.deleted")` |
| identity → negotiation | admin AI toggle + user list | move routes to `console/` |
| catalog → negotiation | admin AI listing authoring | move `admin_listings.py` to `console/` |
| catalog → billing | `discounted_price` on public items | `ask("billing.active_negotiated_price")` |

**`services/` re-homed:** `email_service` → `core/email.py` (transport, no domain knowledge) ·
`shipping_notice` → `domains/billing/` (an order shipping is billing's event) ·
`unread_digest` → `domains/negotiation/` (it buffers messages).

**`conversations`** is the pre-SPEC-043 one-row-per-user chat history, superseded by `messages`
and never dropped. It is assigned to negotiation rather than dropped — deleting a table that
still holds production rows is a separate, destructive decision.

# Test-Driven Development (TDD) Scenarios
- [x] **Acyclic:** a synthetic edge from a lower domain to a higher one fails, naming file and line.
- [x] **Rank is total:** every domain has a rank; a new domain without one fails.
- [x] **Composition root:** a domain importing `console.*` fails; `console/` importing domains passes.
- [x] **`core/` stays at the bottom:** an import of a domain or `console` from `core/` fails.
- [x] **Schema-driven ownership:** a table created in a migration but absent from `TABLE_OWNER`
      fails, with SQL comments stripped so `-- … IF NOT EXISTS so …` is not read as a table.
- [x] **No fourth layer:** a top-level backend package that is not `core`/`domains`/`console`/
      tooling fails.
- [x] **Bus:** a failing subscriber does not propagate; `ask` with no provider returns the default;
      two providers for one query is an error.
- [x] **Behaviour preserved:** thank-you message, shipment line, account purge and
      `discounted_price` all still happen — asserted through the bus, not around it.
- [x] **Config:** `core/env.py` resolves `backend/.env`; importing it twice is idempotent.

# Implementation Files
- `backend/core/bus.py` (new) · `backend/core/email.py` (from `services/`)
- `backend/console/` (new): `__init__.py`, `admin_api.py`, `admin_dashboard.py`, `admin_listings.py`, `admin_ai.py`
- `backend/domains/billing/`: `shipment_notice.py`, `fulfillment.py`, `admin_routes.py`
- `backend/domains/negotiation/`: `unread_digest.py`, `subscribers.py` (new)
- `backend/domains/catalog/routes.py`, `backend/domains/identity/routes.py`, `admin_users.py`
- `backend/core/env.py` (path fix), `backend/core/config.py` (deleted)
- `backend/tests/test_domain_boundaries.py`, `backend/tests/test_core_bus.py` (new)

# Outcome
**24 cycles → 0. 8 back-edges → 0.** Verified by walking the real import graph, not by assertion:

```
[0] identity     -> (none)
[1] catalog      -> ['identity']
[2] billing      -> ['identity', 'catalog']
[3] negotiation  -> ['identity', 'catalog', 'billing']
[4] webhooks     -> (none)
```

**1,919 tests, 90.30% coverage, `ruff` clean.** Route table unchanged (69 operations across 63
paths). Boot unchanged (358–386 ms, **0** LangChain modules) — the bus registers at import, but
every handler defers its domain import to call time.

Found while doing it, and worth knowing:

* **`core/env.py` had been loading a file that does not exist** since SPEC-092 moved it out of
  `backend/`. 41 modules import it. Infisical hides this in every deployed environment, so the only
  place it bites is the one case a `.env` is for — local development without Infisical.
* **Module-level handlers are load-bearing.** A closure defined inside a registrar is a new object
  per call, so re-running the wiring (`importlib.reload(main)`, which several tests do) registered a
  genuine duplicate and the bus correctly refused it. Caught by the tests, not foreseen.
* **`core/email_service.send_shipment_notice` took an order** and imported billing to summarise it.
  It now takes assembled facts: `core/` renders and sends, billing decides what a shipment is.
* The `services/` and `config.py`/`env.py` follow-ups SPEC-092 left open are now closed.

Left open deliberately: `conversations` is owned by negotiation but **not dropped** — it still holds
production rows, and dropping it is a destructive decision that belongs to a human, not this spec.
