# Deploy and roll back

**Goal:** ship a change to production, and undo it if it goes wrong. Reference: [CI/CD](../ci-cd/README.md).

## Deploy

Merge to `main`. `.github/workflows/deploy.yml` looks at what changed:

| Changed | What runs |
|---------|-----------|
| `frontend/**` | lint, typecheck, Vitest → build → Cloudflare Pages |
| `backend/**` | ruff, pytest (88% gate), bandit, pip-audit → image to GHCR tagged with the commit SHA → Lightsail |
| `supabase/migrations/**` | migrations applied to production, before the backend deploys |
| `docs/**` only | nothing |

The backend job waits up to ~3 minutes for the new container to report healthy. If it never
does, the job re-pins the previous image and fails. Deploys are **not** zero-downtime: the
single container restarts, and open SSE streams reconnect on their own.

## Check it

```bash
curl -s https://api.negolah.my/ready       # 200 and "status": "ready"
```

The `uptime` workflow polls `/` and `/ready` every 10 minutes.

## Roll back the backend

**Preferred:** revert the commit on `main`. CI deploys the revert like any other change.

**Faster, by hand:** on the Lightsail host, pin the previous image by SHA:

```bash
sudo env BACKEND_IMAGE_TAG=<previous-commit-sha> docker compose up -d backend
```

Then revert on `main` anyway, or the next deploy will bring the bad commit back.

## Roll back the frontend

In the Cloudflare Pages dashboard, open the project's deployments and choose **Rollback** on the
last good one. Revert on `main` afterwards.

## Roll back a migration

Migrations are forward-only. Write a new migration that undoes the change, and merge it — see
[Apply a database migration](apply-a-database-migration.md).
