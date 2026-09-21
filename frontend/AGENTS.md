# Frontend Agent Guide - Nego-Lah SPA

This directory contains the client application for **Nego-Lah**, built with **Nuxt 4** in **Single Page Application (SPA)** mode (`ssr: false`) and deployed to **Cloudflare Pages**.

---

## Architectural Rules

1. **SPA Architecture (`ssr: false`):**
   - The application is generated as static assets (`bun run generate` -> `.output/public`) served via Cloudflare CDN.
   - Do **NOT** use server-only routes (`server/api/*` that require a Node runtime), Node-specific libraries (`fs`, `net`), or SSR-only cookies.
   - All dynamic requests target the FastAPI backend (`NUXT_PUBLIC_API_BASE_URL`).

2. **UI & Styling Standards:**
   - Use **Nuxt UI** (`@nuxt/ui`) components (`UButton`, `UCard`, `UInput`, `UModal`, `UEmpty` etc.) wherever possible. Use Nuxt UI MCP if uncertain.
   - Style with **TailwindCSS v4**. Do not write ad-hoc raw CSS when Tailwind utility classes suffice.
   - Maintain rich, premium dark/light aesthetics. Ensure accessible contrast and responsive layouts.

3. **Universal Cloudflare Turnstile Bot Protection:**
   - Every page maintains access to a reactive Turnstile token via `useTurnstileToken()`.
   - The Turnstile widget is mounted in the root layout (`app.vue` or `layouts/default.vue`).
   - Authentication flows (`login.vue`, `register.vue`, `forgot-password.vue`) pass the token to `useAuth()`, which forwards it as `X-Turnstile-Token` to the backend's auth routes.
   - Mutating API calls through `useApi()` automatically append the `X-Turnstile-Token` header.

4. **Server-Side Auth (SPEC-093, ADR-0028):**
   - FastAPI brokers every Supabase auth call; the browser holds an opaque `nl_sid` httpOnly
     cookie it cannot read. There is no token in this app and no Supabase client in the bundle.
   - `useAuth()` is the session (`user`, `login`, `logout`, `signInWithProvider`, …); `useApi()`
     is every other call. Both send `credentials: 'include'` and the `X-CSRF-Token` header.
   - Realtime (new messages, typing) arrives on the backend's authenticated SSE stream,
     not a Supabase Realtime channel (SPEC-094).
   - `tests/no-client-side-credentials.test.ts` fails the build if any of this is undone.

5. **Test-Driven Development & LeanSpec:**
   - Implementations are driven by specs in `/docs/specs/SPEC-XXX-<name>.md` (<2,000 tokens).
   - Write unit and component tests using **Vitest** (`frontend/tests/`).
   - Run tests via `bun run test` or `bun test:watch`.
   - All tests must pass before submitting changes.

---

## Useful Commands

```bash
# Start dev server (:3000)
bun dev

# Run Vitest test suite
bun run test

# Run linter
bun run lint

# Run Vue typecheck
bun run typecheck

# Build static SPA output for Cloudflare Pages
bun run generate
```
