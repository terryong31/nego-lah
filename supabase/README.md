# Supabase

Database schema, RLS, and storage policies for Nego-lah, managed with the
[Supabase CLI](https://supabase.com/docs/guides/cli).

## Security model

- The **browser only reads** — and only the `items` table and storage objects.
- **All writes go through the FastAPI backend** using the **service role key**,
  which bypasses RLS. So there are deliberately no write policies for the
  `anon` / `authenticated` roles.
- Authentication actions that stay client-side (Supabase JS, anon key):
  **login, sign-up, password reset** only. Everything else (profile updates,
  avatar upload, email/password change, account deletion, items, orders,
  payments, all admin actions) is server-side.
- The `images` storage bucket is **public-read, client-write denied**.

## Migrations

| File | Purpose |
| --- | --- |
| `20260628000000_baseline_schema.sql` | Core tables (`CREATE TABLE IF NOT EXISTS`, safe on an existing DB). |
| `20260628000100_rls_and_storage.sql` | Enables RLS, `items` public read, storage read-only for clients. |
| `20260628000200_admin_redesign.sql` | Drops the old `admin_users` / `admin_allowed_ips` tables, adds `admin_audit_log`. |

## Admin authentication

There is **no separate admin password table and no IP allowlist**. An admin is just a
Supabase user flagged with `app_metadata.role == "admin"` (set server-side via the
service role — clients cannot write `app_metadata`).

- **Login is two-factor**: password (factor 1) then a 6-digit **email OTP** (factor 2),
  both via Supabase auth. The backend then issues an **opaque, httpOnly session
  cookie** (no JWT in the browser). Revocation is instant via Redis.
- **Promote / revoke an admin** (run from `backend/`, with `backend/.env` populated):

  ```bash
  python -m scripts.promote_admin grant  you@example.com
  python -m scripts.promote_admin revoke you@example.com
  ```

  The account must already exist (normal email/password sign-up). Self sign-up never
  grants admin.
- **Email OTP template**: for the second factor to be a *code* (not a magic link),
  the Supabase **Magic Link** email template must include the `{{ .Token }}` variable.
  Dashboard → Authentication → Email Templates → Magic Link.
- **Same-site requirement**: the admin cookie is `SameSite=Strict`, so the admin UI and
  the API must share a registrable domain (subdomains/ports are fine). For local dev,
  use `http://localhost:3000` (UI) + `http://localhost:8000` (API). If they live on
  different domains, set `ADMIN_COOKIE_SAMESITE=none` and `ADMIN_COOKIE_SECURE=true`.

## Connect & apply

```bash
# 1. Authenticate the CLI (one-time)
supabase login

# 2. Link this directory to your existing project
supabase link --project-ref <your-project-ref>

# 3a. Existing remote DB already has the tables:
#     mark the baseline as applied, then push the rest (RLS/storage + admin redesign).
supabase migration repair --status applied 20260628000000
supabase db push

# 3b. Fresh database (local or new project):
supabase db push        # remote
# or
supabase start          # local stack, applies all migrations automatically
```

The backend reads its config from `backend/.env`: `DATABASE_URL` for the DB and
`ADMIN_SUPABASE_KEY` (service role) for writes / `USER_SUPABASE_KEY` (anon) for
`items` reads and admin auth calls — see `backend/env.py`.
