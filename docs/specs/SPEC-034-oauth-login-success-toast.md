---
id: SPEC-034
title: Success toast on Google sign-in
status: complete
priority: medium
created: 2026-09-06
tags: [identity, auth, frontend, i18n]
assigned: agent
---

# Context & Objectives

Signing in with email + password ends with a "Welcome back!" success toast
(`login.vue`, after `signInWithPassword` resolves). Signing in with Google ends
with nothing: the visitor is bounced through Google, lands back on the app and
is silently signed in. The two paths should confirm success the same way.

The toast cannot be raised where the button is clicked. `signInWithOAuth`
navigates the browser away to Google, so `login.vue` is torn down before the
sign-in has happened — anything queued there dies with the page. The callback is
the only place that knows the sign-in succeeded, and per SPEC-029/032 that is
`pages/confirm.vue`, which OAuth passes through on its way to the target route.

# Acceptance Criteria

- [x] A completed Google sign-in shows the same toast as the password login:
      `auth.loginSuccess` / `auth.loginSuccessDesc`, `color: 'success'`.
- [x] The toast is raised once per callback, not once per `succeed()` signal.
- [x] An email confirmation still gets the "Email Confirmed!" screen and no toast.
- [x] A stray visit to `/confirm` with an existing session toasts nothing —
      nothing was signed in, so claiming a login would be untrue.
- [x] An error callback toasts nothing.
- [x] Existing confirm/login assertions stay green; no new i18n keys.

# Technical Design & Contracts

`pages/confirm.vue` gains `useToast()` and raises the toast inside `succeed()`,
on the branch that already handles "not an email confirmation" — immediately
after the `redirected` latch is set, so the multiple signals that can complete a
callback (`onAuthStateChange`, the `user` watcher, `exchangeCodeForSession`)
produce exactly one toast.

The branch is wider than OAuth: it also carries stray visits. The toast is
therefore gated on positive evidence of a social sign-in:

```ts
isTaggedOAuth || (hasVerificationParam && signedInWithOAuth())
```

`flow=oauth` is set only by `login.vue` on the redirect URL, so the tag alone is
proof. Without it — Supabase configured to return somewhere untagged — a
verification param plus an `amr` of `oauth` says the same thing. A stray visit
has neither and stays silent.

Reuses `auth.loginSuccess` / `auth.loginSuccessDesc`, already present in en/ms/zh.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `?flow=oauth` + session → toast with title `Welcome back!`,
      description `You have logged in successfully.`, `color: 'success'`.
- [x] **Scenario 2:** An untagged callback (`?code=`) whose `amr` is `oauth`
      toasts too.
- [x] **Scenario 3:** The toast fires exactly once when the session arrives via
      several signals.
- [x] **Scenario 4:** `?token_hash=&type=signup` (email confirmation) toasts
      nothing and still renders "Email Confirmed!".
- [x] **Scenario 5:** A stray `/confirm` visit with a password session redirects
      but toasts nothing.
- [x] **Scenario 6:** An `error=access_denied` callback toasts nothing.

# Implementation Files

- `frontend/app/pages/confirm.vue` - raise the toast on the social-login branch
- `frontend/tests/pages/confirm.test.ts` - toast mock and the six scenarios
