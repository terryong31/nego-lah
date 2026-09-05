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
   - Authentication flows (`login.vue`, `register.vue`, `forgot-password.vue`) must pass `captchaToken: token.value` to the Supabase client (`supabase.auth.signInWithPassword`, etc.).
   - Mutating API calls through `useApi()` automatically append the `X-Turnstile-Token` header.

4. **Client-Side Auth & Supabase:**
   - Authentication is managed via `@nuxtjs/supabase` purely on the client.
   - Sessions and JWT tokens are stored client-side in localStorage/cookies.

5. **Test-Driven Development (TDD):**
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
