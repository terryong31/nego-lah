# ADR-0029: CI owns production migrations

- Status: Accepted
- Date: 2026-09-18
- Relates to: [SPEC-096](../specs/SPEC-096-migrations-run-in-cicd.md)

## Context

Production schema changes reached the database by a person running `mise run db:migrate:prod`
from a laptop. Nothing recorded that it happened, nothing ordered it against the deploy that
depended on it, and nothing stopped it happening from an unmerged branch.

The workflow made this worse than it looks. `supabase/**` sat in `paths-ignore` for **both**
`push` and `pull_request`, so a migration-only change triggered no CI at all — no lint, no tests,
no review signal. The riskiest change in the repository was the one change the pipeline ignored.

Two properties of `run_migrations.py` also had no enforcement anywhere. It records the leading 14
digits of a filename as the applied version and skips any version already recorded, so a duplicate
prefix means the second file never executes, and editing a merged migration changes the repository
and not the database. Both failures are silent; neither raises anything.

## Decision

The pipeline applies migrations. Merging a change under `supabase/migrations/` to `main` runs a
`migrate` job before the backend that depends on the new schema is deployed.

- **Pull requests validate, never apply.** `migrations-check` is stdlib-only and holds no
  credential, so a fork PR cannot reach production. It checks the filename convention, version
  uniqueness, and that the diff against the merge base contains only *additions*.
- **Migrations are append-only.** Modification, deletion and rename are rejected. A merged
  migration is already applied somewhere; the only correct edit is a new file.
- **Ordering is explicit.** `deploy-backend` gains `needs: [migrate]` under `always()`, because
  most pushes change no schema and a skipped dependency would otherwise skip the deploy. A
  migration that *failed* blocks it — the running code is the one that matches the old schema.
- **One at a time.** `migrate` carries a global concurrency group rather than a per-ref one, and
  never cancels in progress: queueing behind another migration is correct, interrupting one is not.
- **`environment: production`** is declared so a required-reviewer rule can be added in repo
  settings without editing the workflow. With no rules configured it changes nothing.

`mise run db:migrate:prod` survives as break-glass. It was not deleted because a pipeline that
cannot run is exactly when you need the manual path, but routine use puts the schema ahead of what
any reviewer has seen, and its description now says so.

## Consequences

**The dangerous change is no longer the unreviewed one.** A migration now produces CI output on the
PR that introduces it, which is where a second person can see it.

**Re-running is safe.** Applied versions are recorded and skipped, so a re-run of `migrate` is a
no-op rather than a second application. That is what makes blocking-then-retrying a sane recovery.

**A migration-only push does not redeploy.** `build-backend` is skipped when no backend file
changed, so `deploy-backend` is skipped too, and only the schema moves. This is intended, and it
means an expand-migrate-contract change is two pushes, not one.

**Not addressed.** There is no automatic rollback: a bad migration is fixed by a new migration, not
by reverting a file, and the append-only rule enforces that. There is also no staging gate in the
pipeline — `mise run db:migrate:staging` is still a manual rehearsal.
