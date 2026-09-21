---
id: SPEC-096
title: Supabase Migrations Run in CI/CD, Not From a Laptop
status: complete
priority: high
created: 2026-09-18
tags: [ci-cd, database, migrations, supabase, deployment]
assigned: agent
---

# Context & Objectives
Schema changes reach production by a human running `mise run db:migrate:prod` from their laptop.
That is unreviewed, unlogged, and ordered by whoever remembers to run it — a deploy can ship code
that expects a column nobody applied yet.

Worse, `supabase/**` sits in the workflow's `paths-ignore` for **both** `push` and `pull_request`,
so a migration-only change triggers no CI at all today: no lint, no tests, no review signal.

Objective: merging to `main` applies the migrations, before the backend that depends on them starts.

# Acceptance Criteria
- [x] `supabase/**` no longer sits in `paths-ignore`; a migration change triggers the pipeline.
- [x] A `migrations` output on the `changes` job detects `supabase/migrations/**`.
- [x] **Pull requests validate, never apply.** No PR job holds a production credential.
- [x] A `migrate` job applies `supabase/migrations/*.sql` to production on `push` to `main` only,
      via `infisical export --env=prod --path=/Backend` for `DATABASE_URL`.
- [x] `migrate` runs **before** `deploy-backend`; a migration failure blocks the deploy, and a
      *skipped* `migrate` (no schema change in the push) does not.
- [x] `migrate` carries its own cross-workflow concurrency group so two runs never apply at once.
- [x] Validation fails a PR that: breaks the `YYYYMMDDHHMMSS_name.sql` convention, duplicates a
      version prefix, or **modifies a migration already merged to `main`**.
- [x] `mise run db:migrate:prod` survives as a documented break-glass path, not the normal route.

# Technical Design & Contracts
**Migration filename contract:** `^\d{14}_[a-z0-9_]+\.sql$`. The leading 14 digits are the version
recorded in `supabase_migrations.schema_migrations`; `run_migrations.py` splits on the first `_`,
so a duplicate prefix silently marks a second file as already applied. Uniqueness is a correctness
rule, not style.

**Immutability:** applied versions are skipped by version, never re-read. Editing a merged migration
changes the repo and not the database — the two diverge with no error. CI compares changed files
against the merge base and rejects modification or deletion of an existing migration.

**Job graph (push to `main`):**
```
changes ─┬─> backend-ci ──> build-backend ──┐
         ├─> migrations-check ──> migrate ──┴─> deploy-backend
         └─> frontend-* ──> deploy-frontend
```
`deploy-backend` gates on `needs.migrate.result != 'failure' && != 'cancelled'` under `always()`,
so "skipped because no migration changed" still deploys.

**Secrets:** reuses `INFISICAL_TOKEN`. The `migrate` job declares `environment: production`, so a
required-reviewer rule can be added in repo settings without touching this workflow.

# Test-Driven Development (TDD) Scenarios
- [x] **Convention:** `20260628000000_baseline_schema.sql` passes; `baseline.sql`, `2026_x.sql` and
      `20260628000000_Baseline Schema.sql` each fail with the offending name reported.
- [x] **Uniqueness:** two files sharing a 14-digit prefix fail, naming both.
- [x] **Repo is clean:** the 13 committed migrations pass validation as-is.
- [x] **Immutability:** `changed_existing()` flags a modified/deleted committed migration and
      ignores a newly added one.
- [x] **Workflow wiring:** `supabase` is absent from `paths-ignore`; `migrate` is push-and-main gated;
      `deploy-backend` depends on `migrate`. Asserted against the parsed YAML, not by eye.

# Implementation Files
- `.github/workflows/deploy.yml` — triggers, `migrations` filter, `migrations-check` + `migrate` jobs, deploy gate
- `backend/scripts/validate_migrations.py` — filename/uniqueness/immutability rules
- `backend/tests/test_migration_integrity.py` — the rules above, plus the real migration directory
- `backend/tests/test_ci_workflow.py` — workflow wiring assertions
- `mise.toml` — `db:migrate:prod` redocumented as break-glass

# Outcome
Wiring verified by parsing the workflow (`tests/test_ci_workflow.py`, 18 assertions) and by
`actionlint` + `shellcheck`, both clean. **The pipeline itself has not been executed** — that
happens on the first push, and the first run is the real test of the Infisical path and the
`production` environment.

Worth knowing before that push:
* `supabase/**` was ignored on **both** events, so today a migration-only change runs no CI at
  all. After this, it runs validation, and on `main`, application.
* The `migrate` job needs `DATABASE_URL` at Infisical `--env=prod --path=/Backend`; it is already
  there (it is what `db:migrate:prod` uses).
* `environment: production` is created implicitly on first run with no protection rules, so it
  changes nothing until a reviewer requirement is added in repo settings.
* The 13 committed migrations pass validation unchanged.
