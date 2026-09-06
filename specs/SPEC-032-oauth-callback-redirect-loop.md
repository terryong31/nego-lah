---
id: SPEC-032
title: OAuth callback stranded on the confirming spinner
status: complete
priority: high
created: 2026-09-06
tags: [identity, auth, frontend, routing]
assigned: agent
---

# Context & Objectives

Every Google sign-in ended on `/confirm` showing "Confirming your session, please
wait..." forever — new and existing accounts alike. The session itself was fine:
the header rendered "Hello, <name>" behind the spinner, so the visitor was
signed in but could not leave the callback route without editing the URL.

Root cause is a collision between two pieces of SPEC-029 work:

1. `middleware/auth-redirect.global.ts` inspects `window.location.search` on
   **every** navigation, so that a Supabase callback landing anywhere (or in the
   URL fragment, which `route.query` never sees) is still routed to `/confirm`.
2. `pages/confirm.vue` finishes an OAuth callback with `router.replace('/')`.

The browser URL only catches up once a navigation commits. While that
`router.replace('/')` was in flight the address bar still read
`/confirm?flow=oauth&code=...`, so the middleware re-read the spent `code=`,
concluded a callback was in progress, and redirected to `/confirm` — cancelling
the very navigation that was trying to leave. `confirm.vue` had already latched
its `redirected` flag, so no later signal could retry, and `cleanUrl()` then
stripped the query, leaving the clean `/confirm` URL seen in the bug report.

The unit tests missed it because they mock `router.replace` and never run the
global middleware, so the redirect was asserted as *issued*, never as *landed*.

# Acceptance Criteria

- [x] Completing a Google sign-in leaves `/confirm` and lands on the target page.
- [x] The middleware still routes a callback that arrives on another route
      (`/?code=`, or an implicit-flow `#access_token=`) to `/confirm`.
- [x] The middleware never acts on `window.location` once it is stale.
- [x] The callback URL is cleaned before the redirect is issued, not after.
- [x] A swallowed router navigation can no longer strand the visitor.
- [x] Email confirmation, error and stray-visit paths are unchanged.

# Technical Design & Contracts

**`middleware/auth-redirect.global.ts`** gains two guards:

- `from.path === '/confirm'` returns immediately. Leaving the callback route is
  `confirm.vue` handing control back to the app; it must never be intercepted.
- `window.location` is consulted only when `to.fullPath === from.fullPath`, which
  is Nuxt's initial navigation — the one moment the address bar describes `to`.
  On later navigations `to.query` / `to.hash` are the only authority.

**`pages/confirm.vue`** calls `cleanUrl()` *before* `router.replace(target)`, so
the spent params are gone even if a guard does look, and arms a 2.5s watchdog
that falls back to `window.location.replace(target)` if the page is somehow
still on `/confirm`. A full page load cannot be cancelled by a route guard, and
the session is already established, so it cannot bounce back.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** Navigating `/confirm` → `/` with `?code=` still in
      `window.location` does not redirect.
- [x] **Scenario 2:** An in-app navigation ignores a stale `window.location`.
- [x] **Scenario 3:** The initial navigation still reads `window.location`, so an
      implicit-flow `#access_token=` is routed to `/confirm`.
- [x] **Scenario 4:** `confirm.vue` calls `history.replaceState` before
      `router.replace` on the OAuth path.
- [x] **Scenario 5:** With the router redirect swallowed, the watchdog performs a
      hard navigation to the target.
- [x] **Scenario 6:** The existing 23 confirm/middleware assertions stay green.

# Implementation Files

- `frontend/app/middleware/auth-redirect.global.ts` - skip stale/outgoing reads
- `frontend/app/pages/confirm.vue` - clean before redirect, add the watchdog

# Notes

The lesson for the suite: mocking `router.replace` verifies intent, not arrival.
Anything that navigates out of a route guarded by global middleware needs at
least one assertion that runs the middleware against the navigation.
