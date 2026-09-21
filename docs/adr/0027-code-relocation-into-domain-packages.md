# ADR-0027: Move the code into the domain packages

**Status:** Accepted · **Date:** 2026-09-17 · **Supersedes part of:** [ADR-0002](0002-modular-monolith-over-grpc-microservices.md)

## Context

ADR-0002 chose a modular monolith over microservices, and SPEC-002 named five bounded domains. Both were marked complete. Neither was true of the code.

`domains/` contained 392 lines, 123 of which were re-export stubs. The other 14,700 lines of production code lived in `agent/`, `payment/`, `routes/` and a dozen top-level modules. SPEC-092's first attempt added a service layer *on top* of that arrangement — 437 lines of static-method delegators — which left the structure unchanged and 29 cross-domain table accesses in place. The boundary test it shipped walked only `domains/`, where no file imported another domain, so its assertion body executed zero times and the rule was green by construction.

The lesson: a boundary that is a convention is not a boundary. Two specs had asserted this one for months while it did not hold anywhere.

## Decision

Move the code. A file's bounded context is now **the directory it is in**.

- `items.py` → `domains/catalog/` · `payment/*` → `domains/billing/` · `agent/*` → `domains/negotiation/` · `auth_middleware.py`, `admin_session.py` → `domains/identity/` · each `routes/*` file into the domain that owns its endpoints.
- Shared infrastructure consolidated in `core/`: config, env, cache, connector, logger, limiter, csrf, schemas, notifications, and a new `core/broadcast.py` (realtime chat fan-out, extracted from `payment/fulfillment.py` — it was never a billing concern).
- `agent/`, `payment/` and `routes/` are **deleted**, not shimmed. Re-export shims were considered and rejected: they defeat the repo's `patch_supabase("<module>", …)` testing convention (a monkeypatch would land on the shim, not the real module), and a legacy path that still works is a legacy path that still gets used.
- Cross-domain work goes through the other domain's **package**, which is its contract: `from domains.billing import BillingService`. Importing a module inside another domain is a build failure.
- Code that legitimately spans every domain — the admin console router and the dashboard summary — sits beside `main.py` as `admin_api.py` / `admin_dashboard.py`. A file that needs every domain is not itself a domain.

## Consequences

**The rule is now mechanical.** `tests/test_domain_boundaries.py` derives ownership from the path and AST-scans every `.table("…")` call and every cross-domain import. It fails on a new violation, on a table with no owner, on persistence outside a domain, *and* on a `KNOWN_VIOLATIONS` entry that has been fixed but not deleted. Both directions were verified by injecting violations. The list is empty: 29 cross-domain table accesses → 0, and 24 cross-domain module imports → 0.

**Domain `__init__.py` must stay lazy.** Once logic lives inside a package, an eager router import in `__init__` re-enters the package mid-import. Every domain now exports through `domains/_lazy.py`. This also keeps `agent.bot` — and the LangChain stack behind it, measured at +430 ms and +70 MB RSS per worker against a 1200 MB container running two workers — out of boot.

**Services are extracted, not invented.** Each of the four exists because a caller needed it: catalog's item reads for negotiation and billing, billing's pricing and order access for negotiation and catalog, identity's avatar rule for the negotiation console, negotiation's `chat_settings` and memory for identity's admin screens. Methods with no caller were not written.

**Cost.** ~200 files touched; every import path in the backend changed. The route table is byte-identical (59 operations, 53 paths, diffed against a clean `HEAD` worktree), 1,765 tests pass at 90.10% coverage, and boot cost is unchanged. The test suite needed real edits — patch targets moved with the code, which is the honest consequence of introducing a seam where there was none.

**Not addressed.** `core/config.py` and `core/env.py` still duplicate 27 keys; `services/` (email, digests) is shared across domains and has not been re-homed.
