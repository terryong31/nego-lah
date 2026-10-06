# Documentation Audit — 2026-10-07

Scope: everything under `docs/` (150 files, ~106k words), plus the docs sections of `README.md`.
Method: every claim in the living docs was checked against the code on `fix/non-functional-audit`;
the committed OpenAPI spec was diffed against `app.openapi()`; frontmatter, statuses, headers and
links were parsed across all specs and ADRs. Remediation: [SPEC-102](../specs/SPEC-102-docs-are-checked-like-code.md).

## Summary

The records (ADRs, specs, the non-functional audit) are the strongest part: specific, measured,
honest about trade-offs. The **living docs** were the weakest — they described a backend two
refactors old, and nothing failed when they drifted. The Diátaxis map promised how-to guides that
did not exist.

| Area | Before | After |
|------|--------|-------|
| OpenAPI spec | 53 paths; 12 missing (all `/auth/*`, `/ready`, typing, admin stream), 1 retired route listed | Generated from the app; test fails on drift |
| API guide | Bearer-JWT auth and `@nuxtjs/supabase`, both removed by SPEC-093; ~10 endpoints that do not exist | Cookie + CSRF auth, route groups; no hand-kept endpoint list |
| Architecture / repo | `routes/`, `services/`, `payment/`, `agent/` directories; asyncpg pool; LangGraph supervisor + sub-agents; 10 s lease | Current layers, domain ranking, bus, decide-then-speak, 45 s lease |
| Data model | Two contradictory ER diagrams (`CHAT_MESSAGES`, `PROFILES`); retired `conversations` live; hand-kept migration list 3 files behind | One model from the migrations; Redis keys; storage |
| Workers | Wrong cadence (30 min vs hourly), wrong path, outdated lifespan code pasted in | Three tasks incl. the notification broker; shutdown order |
| Spec statuses | 5 spellings (`complete`, `completed`, `"Draft"`, …); index listed 12 of 101 | Fixed vocabulary, test-enforced; generated index |
| ADR headers | 3 formats; 12 ADRs with no date | One metadata block, test-enforced; generated index; template |
| How-to | None | 5 guides from real scripts and `mise` tasks |
| Links | 2 broken | 0, test-enforced |

## Follow-up findings (resolved the same day)

Each was checked against the code, tests or production before its status changed.

1. **Seven `complete` specs had unticked criteria.** SPEC-001, 003, 007 and 077 were met and are
   now ticked, each citing its test. In SPEC-002 and SPEC-059, criteria that were dropped
   deliberately are now marked *Dropped* with the reason. SPEC-028 went back to `in-progress`:
   production serves its branding assets with `cache-control: no-cache`
   ([#15](https://github.com/terryong31/nego-lah/issues/15)). `test_spec_registry.py` now fails
   when a `complete` spec has an unticked box.
2. **Eight `in-progress` specs and one `draft`.** SPEC-005, 008, 009, 035, 043, 045 and 100 were
   verified and closed. Two exceptions: SPEC-043's two production measurements are marked
   *Deferred*, and SPEC-035's missing `google-oauth-logo.png` was generated. SPEC-093 and SPEC-094
   are live in production (probed); each still waits on a real-browser pass
   ([#14](https://github.com/terryong31/nego-lah/issues/14)).
3. **Docs-only changes skipped CI.** `deploy.yml` now runs a `docs-check` job for them, and
   `test_ci_workflow.py` asserts it.
4. **Stale auth docstrings** on six route handlers and in `llm_factory.py` were rewritten, and the
   OpenAPI spec was re-exported.
5. **`TODO.md`** was deleted. Its open items became issues
   [#14](https://github.com/terryong31/nego-lah/issues/14)–[#18](https://github.com/terryong31/nego-lah/issues/18).
   Completed and declined items were dropped. The Sentry investigation item was not copied into
   the public tracker.
6. **Not changed:** ten specs exceed 2,000 tokens. They are records, so new specs are held to the
   limit instead.

7. **Checked against published practice** (Diátaxis, MADR, GitHub community profile, GitLab's
   docs-testing pipeline). That review added a real tutorial, markdownlint in CI, the MADR
   `Rejected` status, and GitHub's community files. The repository's community profile was 57%
   before: no CONTRIBUTING, code of conduct, or issue or PR templates.

## Industry practices adopted

- **Diátaxis**, honestly applied: explanation, reference and how-to are separate pages, and the
  hub only lists pages that exist.
- **Living docs vs records:** living docs change with the code; ADRs and specs are immutable
  apart from their status line, and are superseded rather than edited.
- **Docs as code:** generated artefacts (OpenAPI, indexes) are produced by a command and checked
  by a test, the same way lockfiles are.
- **ADRs** in Nygard form with a fixed metadata block and an explicit supersession rule.
