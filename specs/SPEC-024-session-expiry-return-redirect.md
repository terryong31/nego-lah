---
id: SPEC-024
title: Session-Expiry Return Redirect — Land Back on the Page You Were Kicked Off
status: completed
priority: high
created: 2026-09-05
tags: [frontend, nuxt, auth, routing, chat]
assigned: agent
---

# Context & Objectives
A buyer sitting on `/chat` (often `/chat?item_id=…`, mid-negotiation) whose Supabase
session lapses gets bounced to `/login`, and after signing back in lands on `/` —
losing the conversation they were in the middle of. SPEC-011 covered *sign-out*
routing; this covers the involuntary *session-expiry* path.

Three separate code paths send an expired visitor to `/login`, and none of them
carries the page the visitor was on:

1. **`useApi()`'s 401 interceptor** — `navigateTo('/login')`, no `redirect` query.
   Every authenticated fetch from `/chat` (history, chat settings, checkout) takes
   this path once the token lapses.
2. **`@nuxtjs/supabase`'s own `global-auth` middleware** — `navigateTo(login)`, bare.
   Nuxt runs global middleware *before* page middleware, so this fires first and the
   `?redirect=` that `middleware/auth.ts` already builds never gets the chance to.
3. **The chat stream itself** — `send()` posts to `/chat/stream` with an empty Bearer
   token when the session is gone, so the send fails with no explanation.

Objective: whichever path fires, the visitor returns to the exact URL (path +
query) they were on once they sign back in.

# Acceptance Criteria
- [x] A 401 (or banned 403) from `useApi()` redirects to `/login?redirect=<current fullPath>`.
- [x] The redirect target is only ever a same-origin path — `//evil.com`, `https://…`
      and non-strings are rejected (no open redirect), and `/` plus the auth pages
      themselves are never used as a return target.
- [x] The supabase module's own guard preserves the blocked page, and `/login` honours
      it when no `?redirect=` query is present.
- [x] Sending a chat message with a lapsed session redirects to
      `/login?redirect=/chat?item_id=…` with a "session expired" toast instead of
      silently failing against the stream endpoint.
- [x] One shared helper backs every `/login` bounce (middleware, `useApi`, chat,
      item page, register, confirm) — the safe-path check is not re-implemented per call site.

# Technical Design & Contracts
`app/utils/auth.ts` gains two exports, next to the existing `isAuthGuarded`:

```ts
safeRedirectPath(value: unknown): string | null   // same-origin paths only
loginRedirect(fullPath?: string | null): { path: '/login', query?: { redirect: string } }
```

`loginRedirect` drops targets not worth returning to (`/` and the auth pages), so a
bare `{ path: '/login' }` still comes out where a redirect would be pointless.

The module's guard is handled with its own supported mechanism rather than being
raced or replaced: `supabase.redirectOptions.saveRedirectToCookie: true` in
`nuxt.config.ts` makes it stash `to.fullPath` in the redirect cookie, and
`login.vue` reads it through `useSupabaseCookieRedirect().pluck()` as the fallback
behind `?redirect=`.

`chat.vue::send()` already re-reads the session before every send (the stale-token
guard). That same read becomes the expiry check: no `access_token` means bail to
`loginRedirect(route.fullPath)` before touching the transport.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** `safeRedirectPath` accepts `/chat?item_id=x`, rejects `//evil.com`,
      `https://evil.com`, `''` and non-strings; `loginRedirect` omits the query for
      `/`, `/login`, `/register`, `/forgot-password`, `/reset-password`, `/confirm`.
- [x] **Scenario 2:** `useApi()`'s 401 handler signs out and navigates to
      `{ path: '/login', query: { redirect: '/chat?item_id=item-1' } }`; from `/` it
      navigates to a bare `{ path: '/login' }`.
- [x] **Scenario 3:** `middleware/auth` keeps its existing `?redirect=` behaviour
      through the shared helper.
- [x] **Scenario 4:** `chat.vue::send()` with no session navigates to
      `/login?redirect=<chat fullPath>`, toasts, and never calls `sendMessage`.
- [x] **Scenario 5:** `/login` with no `?redirect=` query falls back to the supabase
      redirect cookie and pushes there after a successful sign-in; an unsafe cookie
      value falls back to `/`.

# Implementation Files
- `frontend/app/utils/auth.ts` - `safeRedirectPath` / `loginRedirect` helpers.
- `frontend/app/middleware/auth.ts` - use the shared helper.
- `frontend/app/composables/useApi.ts` - carry the current route through the 401 bounce.
- `frontend/app/pages/chat.vue` - explicit lapsed-session bail-out in `send()`.
- `frontend/app/pages/login.vue` - cookie fallback for the return target.
- `frontend/app/pages/register.vue`, `frontend/app/pages/items/[id].vue` - reuse the helper.
- `frontend/app/components/AppHeader.vue`, `frontend/app/pages/confirm.vue` - reuse the helper.
- `frontend/nuxt.config.ts` - `saveRedirectToCookie`.
- `frontend/app/locales/{en,ms,zh}.json` - session-expired toast copy.
- `frontend/tests/{utils/auth,middleware/auth,composables/useApi,pages/chat,pages/login,pages/register,pages/items/id,pages/confirm,components/AppHeader}.test.ts` - coverage.
