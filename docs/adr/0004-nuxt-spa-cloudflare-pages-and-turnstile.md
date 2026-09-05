# 4. Nuxt SPA on Cloudflare Pages with Universal Turnstile Bot Protection

- Status: Accepted
- Date: 2026-09-04
- Deciders: Terry (owner), AI Agent

## Context

The frontend was originally configured for server-side rendering (SSR) via Nitro node-server running in Docker on Lightsail. Running both the FastAPI backend and Nuxt SSR Node process on a 2 GB VPS instance created memory pressure and made frontend deployments dependent on container rebuilds.

Additionally, public store endpoints (account registration, password reset, and AI chat negotiations) required robust bot protection against brute-force attacks and abuse.

### Decision Drivers

- **Zero Host Memory Overhead:** Offload all frontend delivery to Cloudflare Pages edge CDN.
- **Instant Global Edge Delivery:** Static assets served globally from Cloudflare's edge network.
- **Client-Side Supabase Auth:** Auth state is managed in-browser via `@nuxtjs/supabase` without requiring server-side cookie proxying.
- **Universal Bot Defense:** Cloudflare Turnstile provides non-intrusive CAPTCHA challenges to protect auth and AI streams.

## Decision

1. **SPA Architecture:** Set `ssr: false` in `frontend/nuxt.config.ts`. The build produces purely static assets via `bun run generate` into `.output/public`.
2. **Cloudflare Pages:** Deployed directly from GitHub Actions via `cloudflare/wrangler-action`.
3. **Turnstile Integration:**
   - Module `@nuxtjs/turnstile` mounted in `app.vue`.
   - Reusable `useTurnstileToken()` composable managing reactive token state.
   - Forwarding `captchaToken` on `signInWithPassword`, `signUp`, and `resetPasswordForEmail`.
   - Attaching `X-Turnstile-Token` on `useApi` mutation and chat stream calls.
   - Backend verification via FastAPI `verify_turnstile` dependency.

## Consequences

- **Positive:** Lightsail host RAM freed entirely for FastAPI and Redis; instant frontend deploys via Cloudflare Pages; automated bot blocking across the store.
- **Negative:** Search Engine Optimization (SEO) dynamic prerendering is limited compared to full SSR, mitigated via client-side meta tags and static landing pages.
