---
id: SPEC-004
title: Database Connection Pool, Infisical Multi-Folder Secrets, API Domain & Google Tag Manager
status: complete
priority: high
created: 2026-09-04
tags: [database, connection-pool, infisical, api-domain, analytics]
assigned: agent
---

# Context & Objectives
1. **Database Connection Pool**: Audit Supabase Data API (PostgREST HTTP) usage across the stack. The frontend has zero Data API calls. In the backend, 21 modules currently query via `admin_supabase.table(...)`. We establish an `asyncpg` connection pool foundation using `DATABASE_URL` (Supabase pooler on port 6543/5432) to replace HTTP REST with direct binary PostgreSQL pooling.
2. **Infisical Multi-Folder Secrets**: The user created `/frontend` and `/backend` folders in Infisical Cloud. We update `mise.toml` to inject `--path=/backend` for backend tasks and `--path=/frontend` for frontend tasks.
3. **API URL Migration**: Migrate the backend URL in frontend configuration and Caddy from `https://negolah.my/api` to `https://api.negolah.my`, with appropriate CORS and cookie settings.
4. **Google Analytics & Tag Manager**: Add GTM (`GTM-XXXXXX`) and GA4 (`G-XXXXXX`) tracking to the Nuxt SPA with SPA route-change pageview reporting.

# Acceptance Criteria
- [x] Audit report identifies all remaining Supabase Data API call sites.
- [x] `core/database.py` establishes an asynchronous PostgreSQL connection pool using `DATABASE_URL` with connection healthchecks.
- [x] `mise.toml` tasks run with `infisical run --env=dev --path=/backend` (backend) and `--path=/frontend` (frontend) with seamless fallback.
- [x] Frontend default production API base URL points to `https://api.negolah.my`, and backend CORS + cookies allow cross-subdomain interaction.
- [x] Nuxt SPA includes `analytics.client.ts` plugin supporting `NUXT_PUBLIC_GTM_ID` and `NUXT_PUBLIC_GA_ID` with route change tracking.
