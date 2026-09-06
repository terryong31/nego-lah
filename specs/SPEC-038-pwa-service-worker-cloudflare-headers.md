---
id: SPEC-038
title: Progressive Web App (PWA), Cloudflare Pages Headers, CSP, and CORS Security
status: complete
priority: high
created: 2026-09-05
tags: [frontend, backend, pwa, security, cloudflare]
assigned: agent
---

> Renumbered from SPEC-017: three pairs of specs had been filed under the same
> number, which broke traceability. Content unchanged.

# Context & Objectives
Nego-Lah is deployed as a Single Page Application (`ssr: false`) on Cloudflare Pages with an autonomous AI bargaining backend on AWS Lightsail. To deliver an installable, resilient native-like experience while avoiding false-positive blocks from Cloudflare's Web Application Firewall (WAF), Page Shield, or Bot Management:
1. Modern browsers require a registered Service Worker with Workbox precaching and runtime caching strategies for static assets and API requests.
2. Cloudflare Pages requires an explicit `_headers` configuration file to serve `/sw.js` with `no-cache` directives and `Service-Worker-Allowed: /`.
3. Content Security Policy (CSP) must explicitly permit Service Worker registration (`worker-src 'self' blob:; child-src 'self' blob:;`) and background network requests (`connect-src`).
4. Backend CORS must permit requests from Cloudflare Pages domains (`*.pages.dev`) alongside production custom domains (`*.negolah.my`).

# Acceptance Criteria
- [x] `@vite-pwa/nuxt` is installed in `frontend/package.json` and registered in `frontend/nuxt.config.ts`.
- [x] `frontend/public/_headers` declares explicit headers for `/sw.js`, `/workbox-*.js`, `/site.webmanifest`, and global security headers (`Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- [x] CSP includes `worker-src 'self' blob:` and `child-src 'self' blob:` to allow service worker instantiation without browser security violations.
- [x] CSP includes backend API (`https://api.negolah.my`), Supabase, Sentry, Turnstile, and Google Analytics in `connect-src`.
- [x] Workbox configuration denylists `/api/` and `/_console` from SPA navigation fallback.
- [x] Workbox runtime caching specifies non-stale policies (`NetworkFirst` / `NetworkOnly`) for inventory & bargaining endpoints, and cache policies for static assets and fonts.
- [x] `backend/main.py` CORS middleware supports Cloudflare Pages (`*.pages.dev`) and production domains (`*.negolah.my`) via `allow_origin_regex`.
- [x] All frontend and backend tests pass, lint passes with 0 errors, and typecheck passes.

# Technical Design & Contracts
- **`frontend/public/_headers`**:
  ```text
  /sw.js
    Cache-Control: no-cache, no-store, must-revalidate
    Content-Type: application/javascript; charset=utf-8
    Service-Worker-Allowed: /
    Access-Control-Allow-Origin: *

  /workbox-*.js
    Cache-Control: public, max-age=31536000, immutable
    Content-Type: application/javascript; charset=utf-8
    Access-Control-Allow-Origin: *

  /site.webmanifest
    Cache-Control: public, max-age=86400
    Content-Type: application/manifest+json; charset=utf-8
    Access-Control-Allow-Origin: *

  /*
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    Referrer-Policy: strict-origin-when-cross-origin
    Permissions-Policy: camera=(), microphone=(), geolocation=()
    Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://challenges.cloudflare.com https://www.googletagmanager.com https://*.google-analytics.com; worker-src 'self' blob:; child-src 'self' blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self' https://api.negolah.my http://localhost:8000 http://127.0.0.1:8000 https://*.supabase.co wss://*.supabase.co https://*.sentry.io https://challenges.cloudflare.com https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com; frame-src 'self' https://challenges.cloudflare.com https://js.stripe.com; object-src 'none'; base-uri 'self';
  ```
- **`backend/main.py` CORS**:
  - `allow_origin_regex=r"^https://([a-zA-Z0-9_-]+\.)*pages\.dev$|^https://([a-zA-Z0-9_-]+\.)*negolah\.my$"`

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1 (`pwa.test.ts`):** Validate `frontend/public/_headers` exists and specifies `/sw.js` with `no-cache`, `Service-Worker-Allowed: /`, and proper CSP directives (`worker-src`, `child-src`, `connect-src`).
- [x] **Scenario 2 (`pwa.test.ts`):** Validate Nuxt config registers `@vite-pwa/nuxt`, configures Workbox navigation fallback denylist for `/api/` and `/_console`, and establishes runtime caching rules.
- [x] **Scenario 3 (`test_cors.py`):** Assert CORS preflight and requests from `https://nego-lah.pages.dev` and `https://pr-123.nego-lah.pages.dev` receive `Access-Control-Allow-Origin` and `Access-Control-Allow-Credentials: true`.

# Implementation Files
- `specs/SPEC-038-pwa-service-worker-cloudflare-headers.md` - Specification
- `frontend/package.json` - `@vite-pwa/nuxt` dependency
- `frontend/nuxt.config.ts` - PWA and Workbox configuration
- `frontend/public/_headers` - Cloudflare Pages security & service worker headers
- `frontend/app/app.vue` - PWA Manifest component injection
- `backend/main.py` - CORS regex update
- `frontend/tests/pwa.test.ts` - Frontend PWA & headers validation tests
- `backend/tests/test_cors.py` - Backend CORS regex tests
