---
id: SPEC-117
title: Production Log Hygiene, Tool Cleanup, and README Refresh
status: complete
priority: medium
created: 2026-11-26
tags: [logging, observability, dx, docs, cleanup]
assigned: agent
---

# Context & Objectives

Backend production logs across `core/`, `domains/`, and `main.py` still contain early prototype
artifacts: decorative emojis in `logger.*` messages, multi-line `====` ASCII divider banners,
`# LOG:` comment markers, exceptions logged at `INFO` level in `tools/payment.py`, and repeated
mid-function imports in negotiation tools. Because production logging uses structured JSON
(`python-json-logger`), multi-line banners and emoji prefixes pollute log aggregators and make
otherwise solid backend modules look like unreviewed prototype code.

In parallel, `README.md` is refreshed to follow the `othneildrew/Best-README-Template` structure
tailored specifically to Nego-Lah's architecture, benchmarks, and live deployment.

# Acceptance Criteria

- [x] No `logger.*` call in backend production code (`backend/core/`, `backend/domains/`,
      `backend/console/`, `backend/main.py`) contains emoji characters or `====` divider banners.
- [x] Negotiation tool files (`items.py`, `negotiation.py`, `payment.py`) emit concise,
      single-line key-value logs, log caught exceptions at `ERROR` level rather than `INFO`,
      remove `# LOG:` and redundant comments, and hoist patch-safe module imports to top level.
- [x] Automated hygiene test `backend/tests/test_log_hygiene.py` enforces zero emoji/banner
      regressions in backend production `logger.*` calls.
- [x] `README.md` adopts the `Best-README-Template` layout (shields, centered header with logo,
      collapsible Table of Contents, About The Project with screenshot, Built With, Getting
      Started, Usage & Architecture Highlights, Agent Evals, Roadmap, Contributing, License,
      Contact, Acknowledgments) tailored accurately to Nego-Lah.
- [x] All backend tests (including `test_domain_boundaries.py` and coverage >= 88%) and linters
      pass with no behavioral regressions.

# Technical Design & Contracts

- **Log hygiene:** Strip leading/inline decorative emojis (and trailing variation selectors
  `\uFE0F`) from `logger.debug/info/warning/error/exception` calls across production modules.
  User-facing strings (chat replies, email subjects/bodies, tool return strings read by the LLM)
  remain unchanged.
- **Patch-safe top-level imports:** In `domains/negotiation/tools/`, import modules
  (`from core import cache, connector, env, stripe_client`, `from domains.negotiation import context`)
  at module top level so existing `monkeypatch.setattr("core.connector.admin_supabase", ...)`
  and `patch("core.cache.redis_client", ...)` tests continue to work without modification.
- **Boundary compliance:** All cross-domain imports remain package-level
  (`from domains.catalog import CatalogService`, `from domains.billing import BillingService`)
  per SPEC-097.

# TDD Scenarios

1. `test_no_emojis_in_production_logger_calls`: AST-scans all backend production `.py` files
   and fails if any `logger.<level>(...)` string literal or f-string contains emoji codepoints.
2. `test_no_ascii_banner_logs_in_production`: fails if any `logger.<level>(...)` call logs a
   repeated `=` divider banner or leading `\n` banner.
3. `test_no_log_marker_comments_in_production`: fails if `# LOG:` prototype markers exist in
   backend production code.

# Implementation Files

- `backend/tests/test_log_hygiene.py`
- `backend/domains/negotiation/tools/items.py`
- `backend/domains/negotiation/tools/negotiation.py`
- `backend/domains/negotiation/tools/payment.py`
- `backend/core/*.py`, `backend/domains/**/*.py`, `backend/main.py` (emoji log cleanup)
- `README.md`
