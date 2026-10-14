---
id: SPEC-109
title: The Submit Button Waits for Turnstile
status: complete
priority: medium
created: 2026-10-14
tags: [frontend, auth, turnstile, ux]
assigned: agent
---

# Context & Objectives

On sign-in, register, forgot password and the console sign-in, the submit button stayed live while
the Turnstile challenge was unsolved; a click only produced a "complete the security check" toast.
The token handling had two more holes:

- After a submit the console cleared the spent token but never reset the widget, which only
  re-solves on its own 250 s timer. A disabled button would then be stuck for minutes.
- The token lives in a module-level ref, so a token solved on one page unlocked the next page's
  button before that page's widget had run, and an expired token was never dropped.

# Acceptance Criteria

- [x] With Turnstile enabled, the submit button is disabled until the widget yields a token.
- [x] After every submit, success or failure, the token is cleared and the widget reset.
- [x] An expired token is cleared (`expired-callback`).
- [x] Leaving the page clears the token.
- [x] With Turnstile disabled, nothing is gated. The `onSubmit` guard stays as a backstop.

# Technical Design & Contracts

`useTurnstileWidget(action)` wraps `useTurnstileToken()` for pages that render the widget:
`isPending`, the widget `ref` (`reset()`), `options` (`action` and `expired-callback`), and
`spend()`. The buyer forms pass `:submit="{ disabled: isPending }"` to `UAuthForm`; the submit slot is
not overridden.

# TDD Scenarios

- Per buyer page: disabled → solved → enabled; Turnstile off → enabled; failed submit → token
  cleared, `reset()` called, disabled again; `expired-callback` → disabled; unmount → token cleared.
- Console: Continue disabled until solved; a failed attempt resets the widget.

# Implementation Files

- `frontend/app/composables/useTurnstileWidget.ts`
- `frontend/app/pages/{login,register,forgot-password}.vue`, `frontend/app/pages/_console/login.vue`
- `frontend/tests/pages/auth-turnstile-gate.test.ts`, `frontend/tests/pages/_console/login-turnstile.test.ts`
