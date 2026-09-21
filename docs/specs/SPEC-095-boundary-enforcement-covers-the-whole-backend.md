---
id: SPEC-095
title: Boundary Enforcement Covers the Whole Backend
status: complete
priority: medium
created: 2026-09-18
tags: [backend, architecture, modular-monolith, boundaries, testing]
assigned: agent
---

# Context & Objectives
SPEC-092 moved the code into `domains/` and made the boundary mechanical. An audit of the
result found the enforcement has a smaller blast radius than the rule it claims to enforce:

1. **The import rule only runs inside `domains/`.** `test_no_domain_imports_another_domains_private_module`
   walks `DOMAINS.rglob("*.py")`, so production code *outside* a domain is unchecked — and all of it
   is violating. `admin_api.py` reaches into 7 private modules although all 7 have public exports
   created for exactly that purpose; `services/shipping_notice.py` imports `domains.catalog.shipping`
   when `resolve_tracking_url` is a public catalog export; `main.py` imports `domains.billing.payment_state`.
2. **The table scanner is blind to non-literal table names.** It matches `.table("literal")` only.
   `negotiation/services.py` calls `client.table(table)` over a loop variable — benign today, but a
   cross-domain purge written that way passes silently.
3. **`NON_DOMAIN_FILES` is dead weight.** All four exempted files have zero table access, so the
   exemption only weakens `test_all_persistence_lives_inside_a_domain`.

Objective: make the enforced rule equal to the written rule.

# Acceptance Criteria
- [x] The cross-domain private-import rule is enforced across **all backend production code**, not just `domains/`.
- [x] Test/ops tooling (`tests/`, `scripts/`, `evals/`, `conftest.py`) is excluded by a single named
      constant with a stated reason — an eval harness legitimately reads internals.
- [x] `admin_api.py`, `services/shipping_notice.py` and `main.py` import through domain packages.
- [x] `cleanup_expired_payments` is a public `domains.billing` export (it has a non-domain caller).
- [x] Every `.table(…)` call in production code takes a **string literal**; a non-literal fails the build.
- [x] `NON_DOMAIN_FILES` is deleted; no file outside a domain queries a table.
- [x] Full backend suite passes with coverage ≥88%.

# Technical Design & Contracts
- `_PRODUCTION_FILES()` — one generator shared by every scanner, so the table rule and the import
  rule see the same file set. Skips `.venv`, `htmlcov`, `__pycache__`, `migrations` and `_TOOLING`.
- `_TOOLING = {"tests", "scripts", "evals", "conftest.py"}` — dev tooling, exempt by design.
- Import rule: a file may name `domains.<other>` but never `domains.<other>.<module>`. For files
  inside a domain, `<other>` is any domain but its own; for files outside, every domain is foreign.
- New public exports: `domains.billing.cleanup_expired_payments`.

# Test-Driven Development (TDD) Scenarios
- [x] **Backend-wide import rule:** a private cross-domain import anywhere in production code fails,
      verified by injecting one into a non-domain file.
- [x] **Tooling stays exempt:** the same import inside `evals/` does not fail.
- [x] **No dynamic table names:** a `.table(var)` call in production code fails the build.
- [x] **Scanner still matches:** the existing "guard the guard" floor holds after the file set changes.
- [x] **Purge still purges:** `NegotiationService.purge_user_data` deletes from `chat_settings` and
      `messages` and swallows a per-table failure, unchanged by the literal refactor.

# Implementation Files
- `backend/tests/test_domain_boundaries.py` — shared file set, backend-wide import rule, literal-table rule
- `backend/admin_api.py` — import routers and `verify_admin` from domain packages
- `backend/main.py` — import `cleanup_expired_payments` from `domains.billing`
- `backend/services/shipping_notice.py` — import `resolve_tracking_url` from `domains.catalog`
- `backend/domains/billing/__init__.py` — export `cleanup_expired_payments`
- `backend/domains/negotiation/services.py` — literal table names in `purge_user_data`

# Outcome
Enforced backend-wide: **1,893 tests, 90.21% coverage**, `ruff` clean. Boot cost unchanged
(338–378 ms, 0 LangChain modules at import) — `admin_api.py` now resolves its routers through
each domain's `__getattr__` instead of importing the modules directly, which is the same work.

Two things turned up while fixing this and were closed with it:

* `admin_api.py`'s docstring cited `tests/test_admin_gating.py` as proof that every admin data
  route is gated. **That file did not exist.** It does now, and it asserts the property by driving
  unauthenticated requests at all 35 admin routes — this FastAPI version composes router-level
  dependencies at request time, so introspecting `route.dependant` would have reported every one
  of them as ungated and proved nothing. 33 answer 401/403; the 2 that do not are exactly the
  session-establishing routes, named explicitly so a third cannot be added quietly.
* The follow-ups SPEC-092 left open are still open and still unaddressed here: `services/` is a
  fourth layer that is neither a domain nor `core/`, and `core/config.py` / `core/env.py`
  duplicate 27 keys (measured: 34 and 42, 27 overlapping).
