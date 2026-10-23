---
id: SPEC-107
title: The Service Worker Routes No Request the CSP Forbids It to Fetch
status: complete
priority: high
created: 2026-10-12
tags: [pwa, security, frontend]
assigned: agent
---

# Context & Objectives

Item images stopped loading in production. Two correct changes collided:

- SPEC-101 / audit SEC-4 took `*.supabase.co` out of `connect-src` — the browser no longer talks to
  Supabase.
- SPEC-104 anchored the Supabase Storage Workbox rule at `^https://`, so the rule — which had never
  matched a cross-origin URL — started matching.

A plain `<img>` is governed by `img-src` (`https:`), but once Workbox claims the request it re-issues
it with `fetch()`, which is governed by `connect-src`. Every storage image was refused, and
`StaleWhileRevalidate` answered the page with a network error. The Google Fonts rule has the same
defect, dormant only because `@nuxt/fonts` self-hosts every font under `/_fonts`.

This is a hotfix, not the end state. With the rule gone, a storage image loads as a plain `<img>`
under `img-src https:` — the browser still talks to Supabase directly, against the BFF rule
(ADR-0028). Moving user media to a first-party CDN and narrowing `img-src` is SPEC-108.

# Acceptance Criteria

- [x] A storage image URL matches no Workbox rule; the browser loads it under `img-src` and its
      HTTP cache.
- [x] A test fails if any rule claims a cross-origin URL whose origin `connect-src` does not allow.
- [x] The dead Google Fonts rule is removed.
- [x] `connect-src` is unchanged — no Supabase origin returns to it.

# Technical Design & Contracts

Invariant: **a rule may only claim a URL the worker is allowed to `fetch()`.** Same-origin is
always allowed; a cross-origin URL must be allowed by `contentSecurityPolicy({ dev: false })`'s
`connect-src`. Adding a cross-origin cache therefore means widening `connect-src` deliberately, in
the same change.

# TDD Scenarios

- [x] Probe URLs (Supabase storage images, Google Fonts, the R2 media CDN) — every one a rule
      claims must be on an origin `connect-src` allows. Fails on the pre-fix rules.
- [x] Storage image URLs resolve to no rule.

# Implementation Files

- `frontend/pwa/runtime-caching.ts`
- `frontend/tests/pwa-runtime-caching.test.ts`
