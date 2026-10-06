# Apply a database migration

**Goal:** change the Postgres schema safely. CI applies production migrations; you write the
file, rehearse it on staging, and merge. Background: [ADR-0029](../adr/0029-ci-owns-production-migrations.md).

## 1. Write the migration

Create a new file — never edit one that has merged:

```text
supabase/migrations/YYYYMMDDHHMMSS_lower_snake_name.sql
```

- The 14-digit prefix is the version recorded in `supabase_migrations.schema_migrations`. A
  duplicate prefix means the second file never runs.
- Prefer idempotent SQL (`create table if not exists`, `add column if not exists`).
- A new table must be added to `TABLE_OWNER` in `backend/tests/test_domain_boundaries.py`, with
  RLS enabled. Give it a public policy only if the browser genuinely needs it — today only `items`
  has one.
- Columns the client must never read get the treatment `items.min_price` has: revoke the
  table-wide grant and re-grant the safe columns ([ADR-0009](../adr/0009-confidential-columns-enforced-in-postgres.md)).

## 2. Validate

```bash
mise run db:validate      # filename format and version uniqueness — the same check CI runs on a PR
```

## 3. Rehearse on staging

```bash
mise run db:migrate:staging
```

Then run the backend against staging and exercise the feature.

## 4. Merge

Open a PR. On merge to `main`, the `migrate` job in `.github/workflows/deploy.yml` applies pending
migrations to production **before** the backend that depends on them is deployed. If the
migration fails, the backend deploy does not run.

CI rejects a PR that modifies, renames or deletes an existing migration.

## Break glass

`mise run db:migrate:prod` applies migrations to production by hand. Use it only when the pipeline
cannot run, and say so in the PR — it puts the schema ahead of anything a reviewer has seen.

## Update the docs

If the change adds or alters a table, update [Data model](../data/README.md).
