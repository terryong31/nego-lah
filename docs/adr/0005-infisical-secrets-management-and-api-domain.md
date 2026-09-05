# 5. Multi-Folder Infisical Secrets, Dedicated API Domain, and Google Analytics

- Status: Accepted
- Date: 2026-09-04
- Deciders: Terry (owner), AI Agent

## Context

Managing environment variables across development, staging, and production required a unified, auditable secret management workflow. Sensitive credentials for Supabase, Stripe, Google Gemini, Resend, Turnstile, and Sentry needed strict domain separation between frontend and backend.

Simultaneously:
- The backend required a dedicated subdomain (`api.negolah.my`) to cleanly isolate the API service from the static Cloudflare Pages frontend (`negolah.my`).
- Marketing and traffic analysis required Google Tag Manager (GTM) and Google Analytics 4 (GA4) with SPA client-side route navigation tracking.
- Database access required transition from Supabase PostgREST HTTP Data API to persistent PostgreSQL connection pooling via `asyncpg`.

### Decision Drivers

- **Least Privilege Secret Injection:** Frontend should only receive client-safe public keys (`NUXT_PUBLIC_*`), while backend receives private service keys, with Infisical folder paths (`/backend` and `/frontend`).
- **Domain Cleanliness:** `api.negolah.my` for backend services; `negolah.my` for the SPA.
- **Client-Side SPA Analytics:** Proper `page_view` dispatch on Vue Router navigation without duplicate page triggers.
- **Connection Pooling:** Reducing HTTP round-trip latency on database queries by opening persistent binary PostgreSQL connections via `DATABASE_URL`.

## Decision

1. **Infisical Multi-Folder Injection:**
   - Tasks in `mise.toml` invoke `infisical run --env=dev --path=/backend` for backend services and `--path=/frontend` for frontend services, with graceful fallback to local `.env`.
2. **API Subdomain Migration:**
   - Frontend defaults `apiBaseUrl` to `https://api.negolah.my` in production.
   - Caddy reverse-proxies `api.negolah.my` directly to `backend:8000`.
   - Admin session and CSRF cookies support `ADMIN_COOKIE_DOMAIN=.negolah.my` for cross-subdomain sharing.
   - CORS allows `https://negolah.my` and `https://api.negolah.my` with credentials enabled.
3. **Analytics Client Plugin:**
   - Implemented `app/plugins/analytics.client.ts` supporting `gtmId` (`NUXT_PUBLIC_GTM_ID`) and `gaId` (`NUXT_PUBLIC_GA_ID`).
   - Hooks into `router.afterEach` to push `page_view` events with `page_path` and `page_title`.
4. **PostgreSQL Connection Pool:**
   - Installed `asyncpg>=0.30.0` and established asynchronous connection pool lifecycle (`init_db_pool`, `close_db_pool`, `get_db_connection`) in `backend/core/database.py` using `DATABASE_URL`.

## Consequences

- **Positive:** Centralized, auditable secret rotation via Infisical Cloud; clean architectural boundary between API and frontend; automated SPA page analytics; high-throughput database connection pooling.
- **Negative:** Requires Infisical CLI authentication on developer workstations (facilitated via `mise` / Homebrew).
