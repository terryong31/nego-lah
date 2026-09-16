---
id: SPEC-035
title: Distinct Brand Identity, Vector Overhaul, and Google OAuth Compliance
status: in-progress
priority: high
created: 2026-09-06
tags: [frontend, branding, oauth, assets, ui, design]
assigned: agent
---

# Context & Objectives
Google Trust & Safety rejected the Nego-Lah OAuth app verification under the **Branding Guidelines** policy:
> *"Your logo does not uniquely identify your brand and identity. Configure your app with a logo that reflects your identity and does not impersonate any other brand."*

The previous asset set employed a generic speech balloon squircle with a standard sans-serif letter "N", a white dot, and a 4-point star. Single-letter glyphs on standard geometric shapes are flagged by Google reviewers as generic clip art or lacking distinct brand identity. Additionally, Google requires that the logo uploaded to the Google Cloud Console OAuth consent screen matches the logo rendered on the verified website domain and unmistakably represents the application.

This specification establishes:
1. **Custom Vector Brand Mark**: An interlocking negotiation monogram where two conversational speech bubbles (representing buyer and seller/AI) intertwine to form a bespoke "N", centered on an agreement deal sparkle.
2. **Unified Component Integration**:
   - `AppLogo.vue`: Dual-tone emerald-to-mint gradient vector mark with clean brand typography.
   - `mark.svg`: Zero-palette, `currentColor`-only stroke silhouette for `i-nego-mark` chat tool indicators.
   - `spa-loading-template.html`: Inline SVG matching the new geometry with 3D jump-and-spin loading keyframes.
3. **Compliant Public Asset Suite**:
   - `frontend/public/google-oauth-logo.png`: 512×512 (1:1 square) dedicated high-fidelity badge asset featuring the bespoke monogram and explicit "NEGO-LAH" wordmark.
   - Standard PWA & favicon suite (`icon-512.png`, `icon-192.png`, `apple-touch-icon.png`, `favicon.svg`, `favicon.ico`, `og-image.png`).

# Acceptance Criteria
- [ ] `frontend/app/components/AppLogo.vue` renders the new interlocking negotiation monogram SVG with `size` and `hideText` props.
- [ ] `frontend/app/assets/icons/mark.svg` complies with `brandMarkIcon.test.ts` (only `currentColor`, `viewBox` attribute, no hex colors or inline widths/heights).
- [ ] `frontend/app/spa-loading-template.html` renders the new monogram inline with zero external network requests and preserves the 3D flip animation.
- [ ] High-resolution public assets (`google-oauth-logo.png`, `icon-512.png`, `icon-192.png`, `apple-touch-icon.png`, `favicon.svg`, `favicon.ico`, `og-image.png`) generated and placed in `frontend/public/`.
- [ ] All frontend unit tests pass (100%), typecheck passes, and lint passes with 0 errors.

# Technical Design & Contracts
- **Vector Geometry (`AppLogo.vue` / `favicon.svg`)**:
  - ViewBox: `0 0 48 48`
  - Left Bubble / Left Stem: Sweeps down and inward to create the left upright and initial diagonal.
  - Right Bubble / Right Stem: Sweeps up and outward with a conversational pointer notch to create the right upright and closing diagonal.
  - Deal Spark: 4-pointed sparkle positioned at the focal intersection of the two bubbles.
- **Monochrome Mark (`app/assets/icons/mark.svg`)**:
  - Pure vector strokes with `fill="none"` and `stroke="currentColor"`, stroke-width="3", stroke-linecap="round", stroke-linejoin="round".
- **OAuth Screen Badge (`public/google-oauth-logo.png`)**:
  - Dimensions: 512×512 PNG, square, <1MB.
  - Background: Gradient emerald rounded squircle (`#064e3b` to `#022c22`).
  - Foreground: High-contrast interlocking negotiation monogram and high-legibility "NEGO-LAH" typography.

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1 (`AppLogo.test.ts`):** Assert SVG brand mark renders the new path geometry, verifies `size` variants (`sm`, `md`, `lg`), and respects `hideText`.
- [ ] **Scenario 2 (`brandMarkIcon.test.ts`):** Assert `mark.svg` exists, uses only `currentColor`, has no hex values or gradient tags, and is sized exclusively by `viewBox`.
- [ ] **Scenario 3 (`spaLoadingTemplate.test.ts`):** Assert `spa-loading-template.html` retains `id="__nuxt-loader"`, inline CSS, no external resources, and renders the updated SVG mark.
- [ ] **Scenario 4 (`pwa.test.ts`):** Assert manifest and public icon paths remain fully functional.
