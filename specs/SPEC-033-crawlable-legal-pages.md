---
id: SPEC-033
title: Crawlable legal pages for Google OAuth verification
status: complete
priority: high
created: 2026-09-06
tags: [frontend, seo, compliance, identity]
assigned: agent
---

# Context & Objectives

Google OAuth verification rejected the app:

> Your privacy policy page at "https://negolah.my/privacy" does not have
> sufficient content.

Two independent causes, both real:

1. **The page served no content at all.** The frontend is an SPA (`ssr: false`)
   deployed as static files to Cloudflare Pages, and only `/` was prerendered, so
   `/privacy` fell back to the app shell. `curl https://negolah.my/privacy`
   returned 18 characters of visible text — "Nego-Lah Nego-Lah". Anything that
   does not execute JavaScript, the reviewer included, read a blank page.
2. **The policy was thin.** Seven short sections that never mentioned Google
   sign-in, the data received from it, the Limited Use commitment, retention
   periods, deletion, international transfers, cookies, or the AI processing that
   sends negotiation messages to Gemini.

# Acceptance Criteria

- [x] `GET /privacy` returns the full policy text in the response body, with no
      JavaScript executed.
- [x] `/terms` is fixed the same way.
- [x] The policy discloses the Google user data received (name, email, picture,
      account id), the scopes requested, and the purpose of each field.
- [x] It carries the Limited Use statement and links to the Google API Services
      User Data Policy and to the permissions revocation page.
- [x] It documents sharing, retention, deletion, transfers, cookies, security,
      children and contact.
- [x] Every statement is true of the deployed system.
- [x] Users still get the normal in-app page; the SPA architecture is unchanged.
- [x] One source of text — the crawler's copy cannot drift from the user's.

# Technical Design & Contracts

A per-route `ssr: true` route rule does **not** work: a global `ssr: false` build
has no server renderer, so Nitro prerenders an empty `#__nuxt` shell regardless.
Flipping the app to `ssr: true` was rejected — it breaks the static Cloudflare
Pages deploy and the SPA invariant in AGENTS.md §4.

Instead the text is injected into the prerendered HTML at build time:

- `app/utils/legal.ts` holds `PRIVACY_POLICY` and `TERMS_OF_SERVICE` as markup
  plus `renderLegalDocument()`. Single source of truth.
- `pages/privacy.vue` / `pages/terms.vue` render that string, so the in-app page
  is unchanged for users.
- `routeRules` prerenders `/privacy` and `/terms`, which makes Cloudflare Pages
  serve a real file per route instead of the SPA fallback.
- `build/legal-prerender.ts` exports `injectLegalDocument(route, contents)`,
  called from the `prerender:generate` hook in `nuxt.config.ts`. It replaces the
  empty `<div id="__nuxt"></div>` with the rendered document, and **throws** if
  that anchor stops matching — a silent miss would ship the blank page again.
  Extracted from nuxt.config, like `pwa/runtime-caching.ts`, so it is testable.

Vue's `mount()` empties the container before its first render (it is mounting,
not hydrating), so the injected markup is discarded the moment the SPA boots.
The `#__nuxt-loader` overlay is `position: fixed; z-index: 999999`, so nothing
flashes on screen either.

Measured: `/privacy` visible text goes from 18 to 11,279 characters.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `injectLegalDocument` inlines the policy into a real shell.
- [x] **Scenario 2:** It raises the page from under 50 to over 5,000 characters.
- [x] **Scenario 3:** The `#__nuxt` id and attributes survive, so Vue still mounts.
- [x] **Scenario 4:** `/terms` is injected too, and a trailing slash is tolerated
      (Cloudflare Pages 308-redirects `/privacy` to `/privacy/`).
- [x] **Scenario 5:** Every other route is left untouched.
- [x] **Scenario 6:** A changed anchor throws `LegalPrerenderError`.
- [x] **Scenario 7:** The page renders all 13 sections in order.
- [x] **Scenario 8:** The Google data fields, scopes, Limited Use statement and
      both Google links are present.
- [x] **Scenario 9:** Sharing, retention and deletion statements are present.

# Implementation Files

- `frontend/app/utils/legal.ts` - the policy and terms text, one source
- `frontend/app/pages/privacy.vue` - renders the shared document
- `frontend/app/pages/terms.vue` - renders the shared document
- `frontend/build/legal-prerender.ts` - build-time injection, testable
- `frontend/nuxt.config.ts` - prerender rules + `prerender:generate` hook
- `frontend/tests/legal-prerender.test.ts` - injection assertions
- `frontend/tests/pages/privacy.test.ts` - verification-requirement assertions

# Notes

Facts were read from the codebase rather than assumed: Gemini failover
(`backend/agent/llm_factory.py`, ADR-0003), Resend for email, Stripe, Supabase,
Sentry replay sampling and masking (`sentry.client.config.ts`: 5% of sessions,
100% of error sessions, `maskAllText`/`maskAllInputs`/`blockAllMedia` in prod),
Cloudflare Turnstile, and the deletion behaviour in `backend/routes/user.py`
(profile, chat settings and conversations removed; orders retained as business
records). No claim is made about Gemini training practices, which we cannot
verify from here.

Re-submit for verification after deploying. The reviewer re-fetches the URL.
