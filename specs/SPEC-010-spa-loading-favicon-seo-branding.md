---
id: SPEC-010
title: SPA Loading Template, Favicon, SEO Meta, and Top Nav Logo
status: complete
priority: high
created: 2026-09-05
tags: [frontend, branding, seo, performance]
assigned: agent
---

# Context & Objectives
Nego-Lah is deployed as a Single Page Application (`ssr: false`) on Cloudflare Pages. Because client-side hydration takes a few hundred milliseconds before Vue executes, users can experience a blank screen or unbranded flash. Furthermore, the application currently lacks a custom vector favicon, comprehensive SEO metadata (OpenGraph, Twitter card, theme colors, manifest), and a distinct SVG brand logo in the top navbar.

This specification establishes:
1. **SPA Loading Template (`app/spa-loading-template.html`)**: Zero-JS, inline-CSS, light/dark theme-adaptive loading splash screen displaying the brand mark and indeterminate progress bar.
2. **Top Nav Left Brand Logo (`AppLogo.vue` / `AppHeader.vue`)**: A distinctive vector logo mark (combining negotiation dialogue + price tag) with styled "Nego-Lah" typography.
3. **Favicon Suite & Web App Manifest**: SVG vector favicon with dark-mode preference support, fallback `favicon.ico`, Apple Touch Icon, and `site.webmanifest`.
4. **Comprehensive SEO Meta**: Nuxt `app.head` baseline and `app.vue` dynamic metadata supporting OpenGraph, Twitter cards (`summary_large_image`), custom OG banners, locale tags, and search indexing.

# Acceptance Criteria
- [x] `frontend/app/spa-loading-template.html` is configured in `nuxt.config.ts` via `spaLoadingTemplate`.
- [x] SPA loading template renders with pure inline CSS, 0 external font/image requests, and auto-adapts to `prefers-color-scheme: dark` and `light`.
- [x] Accessible status role (`role="status"` and `aria-label`) present in the loading template.
- [x] `frontend/app/components/AppLogo.vue` renders an SVG brand mark with optional text and configurable size props (`sm`, `md`, `lg`).
- [x] `AppHeader.vue` displays `AppLogo` on the left side of the top navbar, linking cleanly to `/`.
- [x] Public favicon suite generated in `frontend/public/` (`favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `site.webmanifest`, `og-image.png`).
- [x] `nuxt.config.ts` declares baseline `app.head` metadata (charset, viewport, description, theme-color, OpenGraph, Twitter, favicon links).
- [x] Trilingual i18n taglines and titles dynamically populate SEO tags in `app.vue`.
- [x] All frontend unit tests pass (100%), typecheck passes, and lint passes with 0 errors.

# Technical Design & Contracts
- **`app/spa-loading-template.html`**:
  ```html
  <div id="__nuxt-loader" role="status" aria-label="Loading Nego-Lah">
    <div class="loader-content">
      <svg class="loader-logo" ...>...</svg>
      <div class="loader-title">Nego-Lah</div>
      <div class="loader-bar"><div class="loader-indicator"></div></div>
    </div>
  </div>
  ```
- **`nuxt.config.ts`**:
  `spaLoadingTemplate: 'spa-loading-template.html'` and `app.head` config.
- **`components/AppLogo.vue`**:
  Props: `size?: 'sm' | 'md' | 'lg'`, `hideText?: boolean`. Emits standard click/link behaviors.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1 (`AppLogo.test.ts`):** Mount `AppLogo`, verify SVG icon mark and "Nego-Lah" text render, verify `hideText` omits text, verify size prop classes.
- [x] **Scenario 2 (`AppHeader.test.ts`):** Verify `AppHeader` renders `AppLogo` component within the `#left` brand slot.
- [x] **Scenario 3 (`spaLoadingTemplate.test.ts`):** Assert `app/spa-loading-template.html` exists, contains `id="__nuxt-loader"`, inline `<style>`, no external network URLs (`http://` or `https://`), and includes `prefers-color-scheme`.
- [x] **Scenario 4 (`app.test.ts`):** Assert SEO meta tags and favicon links are properly configured and registered.

# Implementation Files
- `specs/SPEC-010-spa-loading-favicon-seo-branding.md` - Specification
- `frontend/app/spa-loading-template.html` - Inline SPA loading template
- `frontend/app/components/AppLogo.vue` - Brand logo component
- `frontend/app/components/AppHeader.vue` - Top navbar logo integration
- `frontend/public/favicon.svg` - Responsive vector favicon
- `frontend/public/favicon.ico` - Multi-size ICO
- `frontend/public/apple-touch-icon.png` - iOS home icon
- `frontend/public/og-image.png` - High-resolution 16:9 Twitter / OG banner
- `frontend/public/site.webmanifest` - Web App Manifest
- `frontend/nuxt.config.ts` - Head & spaLoadingTemplate configuration
- `frontend/app/app.vue` - SEO meta integration
- `frontend/tests/components/AppLogo.test.ts` - Logo component tests
- `frontend/tests/spaLoadingTemplate.test.ts` - Template validation tests
