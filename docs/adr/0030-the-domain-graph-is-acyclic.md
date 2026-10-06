# ADR-0030: The domain graph is acyclic

- Status: Accepted
- Date: 2026-09-20
- Extends: [ADR-0027](0027-code-relocation-into-domain-packages.md)
- Relates to: [SPEC-097](../specs/SPEC-097-the-domain-graph-is-acyclic.md)

## Context

ADR-0027 moved the code into `domains/` and made the boundary a directory. SPEC-095 extended the
import rule to the whole backend. Both hold. Neither asks the question that decides whether this is
a modular monolith: **should this dependency exist?**

It did not hold. The four live domains formed a fully connected cyclic graph — **24 distinct cycles
over 8 back-edges**. `catalog ↔ billing`, `catalog ↔ negotiation`, `billing ↔ negotiation`,
`identity ↔ negotiation`. Every rule in place passed, because each checked *how* a domain imported
another (the package, not a module inside it) and none checked whether it should at all. Nothing
could be reasoned about, tested or extracted alone. That is a distributed ball of mud with
directory labels, and it is what "modular monolith" had been describing.

Three related facts surfaced with it. `conversations` existed in the schema with no owner, because
`TABLE_OWNER` was only ever checked against tables some file happened to query. `services/` was a
fourth layer — neither a domain nor infrastructure — that four domains imported. And `core/env.py`,
which 41 modules import, had been loading `backend/core/.env` since SPEC-092 moved it out of
`backend/`: `dirname(__file__)` followed the file. Production never noticed, because Infisical
injects the variables; local development without Infisical is the only reason the file exists.

## Decision

**Rank the domains and let dependencies run one way.**

```
identity (0)  <  catalog (1)  <  billing (2)  <  negotiation (3)
```

An order needs an item, so billing is above catalog. The agent needs both, so negotiation is on
top and nothing may depend on it. A domain may import strictly below itself; anything else fails
the build, along with any cycle, stated independently so that editing a rank cannot legalise one.

**Upward work goes through `core/bus.py`, never an import.** Two primitives, because there are two
honest shapes of upward call:

- `emit` / `on` — something happened and a higher domain may care. Billing settles a payment;
  whether that becomes a chat message is not billing's business. Fan-out, no return, and a failing
  subscriber never reaches the emitter — `purchase.fulfilled` is emitted from inside the Stripe
  webhook *after* the money moved, so a chat outage must not fail that webhook and have Stripe
  redeliver a fulfilled payment.
- `ask` / `provides` — a lower domain needs one fact a higher one owns. Catalog shows a buyer their
  negotiated price without knowing billing exists. One provider; its errors propagate, because the
  caller is waiting on the answer and a swallowed failure returns a wrong number rather than none.
  With nothing registered, `ask` returns the caller's default and the storefront renders list price.

**A screen that needs two domains is composition, not a domain.** `console/` is the composition
root: it may import every domain and no domain may import it. `admin_api.py` and
`admin_dashboard.py` moved there, `admin_listings.py` (catalogue + the agent's vision tools) left
catalog, and identity's `/users/{id}/ai` routes became `console/admin_ai.py` while the rest of
`/users` stayed in identity. Splitting a router is normal; the alternative was identity calling up.

**Three layers, and `services/` is not one of them.** `email_service` → `core/` (it renders and
sends; it no longer knows what an order is — the caller passes assembled facts), `shipping_notice`
→ billing, `unread_digest` → negotiation.

**Ownership is driven by the schema.** Every table a migration creates must appear in
`TABLE_OWNER`, so a table nobody queries still has an owner. `conversations` — pre-SPEC-043 chat
history, superseded by `messages` — is assigned to negotiation rather than dropped: deleting a
table that still holds production rows is a separate, destructive decision.

## Consequences

**The graph is now a DAG**: 24 cycles → 0, 8 back-edges → 0, verified by walking the real imports
rather than by assertion. `identity` depends on nothing; `webhooks` depends on nothing.

**Enforcement matches the claim.** `tests/test_domain_boundaries.py` fails on a back-edge, a cycle,
a domain importing `console/`, a `core/` import of either, a table with no owner, a `TABLE_OWNER`
entry for a table no migration creates, and a fourth top-level layer.

**Cost.** 1,919 tests at 90.30% coverage, `ruff` clean. The route table is unchanged (69 operations
across 63 paths) and boot is unchanged (358–386 ms, zero LangChain modules imported).

**The bus is wired at import, not in the lifespan.** The test suite drives the app without running
the lifespan, and wiring that only exists in production is wiring nobody tests.

**Handlers must be module-level.** A closure defined inside a registrar is a new object on every
call, so re-running the wiring — which `importlib.reload(main)` does in several tests — registers a
genuine duplicate. This was found by those tests, not reasoned about in advance.

**Not addressed.** `conversations` is owned but not dropped. The bus is synchronous and in-process
by design (2 GB Lightsail, AGENTS.md §3): a slow subscriber slows its emitter, and anything slow
belongs in a lifespan loop instead.
