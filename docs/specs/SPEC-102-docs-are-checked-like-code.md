---
id: SPEC-102
title: Docs Are Checked Like Code
status: complete
priority: medium
created: 2026-10-07
tags: [docs, ci, api, repo]
assigned: agent
---

# Context & Objectives
A documentation audit ([2026-10-07](../audits/2026-10-07-documentation-audit.md)) found the
living docs describing a backend that no longer exists: `routes/`, `services/`, `payment/` and
`agent/` directories, an `asyncpg` pool, Supabase JWT bearer auth, a LangGraph supervisor with
sub-agents, a 10 s LLM lease. The committed `openapi.json` was missing 12 of 64 paths (all of
`/auth/*`, `/ready`, the typing endpoints) and still listed the retired SSE ticket route. Spec
statuses used five spellings, the spec index listed 12 of 101, and the Diátaxis map advertised
how-to guides that were never written.

Nothing failed when any of this drifted. This spec makes the drift that can be machine-checked a
test failure, and rewrites the living docs against the code.

# Acceptance Criteria
- [x] `docs/api/openapi.json` equals `app.openapi()`; a test fails when a route changes without a re-export (`mise run docs:openapi`).
- [x] Every relative link in `docs/`, `README.md` and `AGENTS.md` resolves; a test fails on a broken one.
- [x] Spec `status:` is one of `draft | in-progress | complete | abandoned | superseded`; required frontmatter keys are present.
- [x] `docs/specs/README.md` and `docs/adr/README.md` indexes are generated and a test fails when stale (`mise run docs:index`).
- [x] Every ADR opens with the same metadata block (`Status`, `Date`) and the ADR index is built from it.
- [x] Living docs (architecture, data, api, repo, workers, flows) match the code; records (specs, ADRs, audits) are point-in-time and say so.
- [x] `docs/how-to/` holds task guides for the operations that exist as scripts or `mise` tasks.
- [x] A getting-started tutorial (Diátaxis classes environment setup as a tutorial, not a how-to).
- [x] Docs-only changes run a `docs-check` CI job: markdownlint on the living docs plus the tests above.
- [x] A `complete` spec has no unticked criterion; ADR status follows the MADR lifecycle (adds `Rejected`).
- [x] GitHub community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, PR template, issue forms.
- [x] Vale prose lint (product terms are errors; marketing and condescending words are warnings), pinned in `mise.toml` and run in CI.
- [x] An advisory stale-docs report: each living doc is mapped to the code it describes; CI annotates docs older than that code.
- [x] A Playwright e2e suite (`frontend/e2e/`): anonymous contract checks always, session checks when credentials are provided (#14).

# Technical Design & Contracts
- `backend/scripts/docs_tools.py` — `openapi` writes the spec (sorted keys, 2-space indent,
  trailing newline); `index` rewrites the region between `<!-- BEGIN GENERATED -->` and
  `<!-- END GENERATED -->` in both index READMEs. Pure functions (`render_spec_index`,
  `render_adr_index`, `openapi_document`) are what the tests call.
- ADR metadata block, parsed by `docs_tools.adr_metadata`:
  ```
  # ADR-NNNN: Title
  - Status: Accepted | Superseded by ADR-NNNN | Deprecated | Proposed
  - Date: YYYY-MM-DD
  ```
- Living docs describe the system as it is now; when behaviour changes, edit them. Records are
  never rewritten for content, only their status line.

# TDD Scenarios
- [x] **OpenAPI drift:** committed spec ≠ `app.openapi()` → fail with the added/removed paths.
- [x] **Links:** a `](missing.md)` in any doc → fail naming file and target.
- [x] **Status vocabulary:** `status: completed` → fail.
- [x] **Index freshness:** a spec not in `specs/README.md` → fail.
- [x] **ADR metadata:** an ADR with no `- Status:` line → fail.

# Implementation Files
- `backend/scripts/docs_tools.py` — generators.
- `backend/tests/test_docs.py` — link, OpenAPI, index and ADR checks.
- `backend/tests/test_spec_registry.py` — status vocabulary and required keys.
- `mise.toml` — `docs:openapi`, `docs:index`, `docs:lint`; `.markdownlint-cli2.jsonc`.
- `.github/workflows/deploy.yml` — `docs` filter and `docs-check` job; `backend/tests/test_ci_workflow.py`.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/`.
- `docs/**` — rewritten living docs, `how-to/`, `adr/TEMPLATE.md`, normalised ADR headers.
