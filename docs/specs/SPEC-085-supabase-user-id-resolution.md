---
id: SPEC-085
title: Supabase User ID Resolution
status: complete
priority: high
created: 2026-09-15
tags: [frontend, auth, notifications, i18n]
assigned: agent
---

# Context & Objectives

`@nuxtjs/supabase` populates `useSupabaseUser()` from `client.auth.getClaims()`, so the ref
holds a **JWT payload**, not a `User` object. `confirm.vue` already documents this ("it is the
JWT payload"), and `JwtPayload` carries the user id as **`sub`** — `RequiredClaims` is
`{iss, sub, aud, exp, iat, role, aal, session_id}`. There is no `id`.

Ten call sites read `user.value?.id`. That expression is `undefined` at runtime, and it
typechecks only because `JwtPayload` declares `[key: string]: any`. The consequences are
silent:

- `useNotifications.connect()` returns early on `!user.value?.id`, so the SSE notification
  stream **never opens**;
- `useLanguage.syncLanguageToServer()` returns early, so a language choice is never persisted
  to the account.

Nothing went red, for two reasons: the index signature defeats the typechecker, and the unit
tests mock the user as `{ id: 'user-1' }` — encoding the wrong shape and passing against it.
`profile.vue` and `orders.vue` had already hit this and worked around it locally by preferring
`session.user.id`, which is corroboration rather than a fix.

**Objective:** resolve the user id in one place, from the claim that actually carries it.

# Acceptance Criteria

- [x] **One resolver:** `resolveUserId(user)` in `app/utils/auth.ts`, beside `resolveAvatarUrl`
      which exists for the same reason.
- [x] **Reads `sub` first:** falls back to `id` so a `User`-shaped object (what
      `supabase.auth.getSession()` returns, and what `profile.vue` / `orders.vue` pass) still
      resolves.
- [x] **Every call site uses it:** `useNotifications` (4), `useLanguage` (3), `orders.vue` (2),
      `profile.vue` (1), `plugins/item-store-identity.client.ts` (1).
- [x] **Tests assert the real shape:** the notification and language tests drive a `sub`-shaped
      claims object, not `{ id }`.
- [x] **Null-safe:** `null` / `undefined` / an object with neither key resolve to `null`, so a
      signed-out ref still short-circuits every guard exactly as before.

# Technical Design & Contracts

```ts
// app/utils/auth.ts
export interface UserIdLike { sub?: string | null, id?: string | null }

export function resolveUserId(user: UserIdLike | null | undefined): string | null {
  return user?.sub ?? user?.id ?? null
}
```

Invariant: no call site reads `.id` off `useSupabaseUser()` directly.

# TDD Scenarios

- [x] **S1:** `resolveUserId({ sub: 'u1' })` -> `'u1'` (the claims shape).
- [x] **S2:** `resolveUserId({ id: 'u1' })` -> `'u1'` (the `User` shape from `getSession()`).
- [x] **S3:** `sub` wins when both are present.
- [x] **S4:** `null`, `undefined` and `{}` all resolve to `null`.
- [x] **S5:** `useNotifications` opens its stream for a `sub`-shaped user — the regression
      that had it permanently closed.
- [x] **S6:** no source file reads `user.value?.id` off `useSupabaseUser()` any more.

# Implementation Files

- `frontend/app/utils/auth.ts`
- `frontend/app/composables/useNotifications.ts`
- `frontend/app/composables/useLanguage.ts`
- `frontend/app/pages/orders.vue`, `frontend/app/pages/profile.vue`
- `frontend/app/plugins/item-store-identity.client.ts`
- `frontend/tests/utils/auth.test.ts`
