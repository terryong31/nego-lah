# Grant or revoke admin access

**Goal:** let an existing account into the seller console at `/_console`, or take that access away.

Admin access is two things kept in sync by one script: `app_metadata.role = "admin"` on the
Supabase user (authoritative) and an entry in a Redis allowlist (instant to revoke). Signing up
never grants it.

## Prerequisites

- The person already has a normal account (email and password).
- Secrets for the target environment — Infisical, or `backend/.env` for local.

## Grant

```bash
cd backend
infisical run --env=dev --path=/Backend -- uv run python -m scripts.promote_admin grant person@example.com
```

Use `--env=prod` for production. Without Infisical, drop the `infisical run … --` prefix and the
script reads `backend/.env`.

They can now sign in at `/_console/login`: password, then a one-time code sent by email.

## Revoke

```bash
infisical run --env=prod --path=/Backend -- uv run python -m scripts.promote_admin revoke person@example.com
```

Revoking clears the role and the allowlist entry, so the next admin request from any of their sessions is
rejected.

## Related

- `scripts/unban_user.py` — lift a ban set from the console.
- `scripts/revoke_all_sessions.py` — sign **everyone** out; in production run it through the
  `ops-revoke-sessions` workflow, not by hand. See [CI/CD](../ci-cd/README.md).
