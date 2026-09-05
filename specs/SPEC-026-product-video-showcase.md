---
id: SPEC-026
title: Product Walkthrough Video Showcase
status: complete
priority: high
created: 2026-09-06
tags: [frontend, video, home, ux, memphis]
assigned: agent
---

# Context & Objectives

The landing page previously used a 300vh scroll-pinned text dialogue demo (`NegotiationDemo.vue`), which required visitors to scrub through five dialogue bubbles manually. This only conveyed the negotiation dialogue and failed to showcase the actual end-to-end product flow.

Visitors need to see the authentic product journey:
1. Exploring listings from the catalog
2. Initiating live AI price negotiation on a product page
3. Autonomous counter-offering and agreed price confirmation
4. Stripe checkout handoff
5. Order tracking and shipping details confirmation

This specification details replacing the scroll-pinned section with a cinematic, non-controlled **Product Walkthrough Video Showcase** component (`ProductVideoShowcase.vue`) that plays autonomously on viewport entry and frames the demo with Corporate Memphis design accents.

---

# Acceptance Criteria

- [x] **Autonomous Playback Engine**:
  - Plays MP4/WebM video asset (`/videos/negotiation-demo.mp4`, with fallback poster image `/images/hero-illustration.jpg`).
  - Automatically plays (muted, looping) when scrolled into view via `IntersectionObserver` (>= 25% threshold); pauses when scrolled out of viewport.
  - Video is non-interactive (`pointer-events-none`, `tabindex="-1"`, no manual controls or scrubber overlays) for a clean, living-canvas experience.
- [x] **Corporate Memphis Framing**:
  - Framed with floating Corporate Memphis SVGs matching `UHero` and `MemphisCharacters.vue`:
    - Top-Left: Orange arch & pink dot (`#FB923C` / `#F43F5E`) with `animate-memphis-float`
    - Top-Right: Rotating 8-point yellow sunburst star (`#FBBF24`) with `animate-memphis-spin-slow`
    - Left Edge: Purple zigzag ribbon (`#A855F7`) with `animate-memphis-float-reverse`
    - Bottom-Left: Colorful dotted matrix with `animate-memphis-pulse-subtle`
    - Bottom-Right: Cyan donut & pink confetti pill (`#06B6D4` / `#EC4899`) with `animate-memphis-float`
  - Deep ambient backlight glow gradient behind the video frame (`from-primary/20 via-emerald-500/10 to-purple-500/20`).
  - Subtle rounded glassmorphism border (`rounded-2xl sm:rounded-3xl border border-default/60`).
- [x] **Streamlined Layout (No 3-Card Block)**:
  - The 3-card journey block is removed beneath the video to keep the section punchy and focused purely on the video showcase.
- [x] **Zero Regressions & Clean Integration**:
  - Replaces `<HomeNegotiationDemo />` in `frontend/app/pages/index.vue`.
  - Full i18n support for title, subtitle, and badges in English, Malay, and Chinese.
  - Clean fallbacks when video file is not yet dropped into `public/videos/`.

---

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** Component renders `#how-it-works` section with badge, headline, and Memphis wave underline.
- [x] **Scenario 2:** Renders autonomous `<video>` element with `playsinline`, `autoplay`, `loop`, `muted`, and `pointer-events-none`.
- [x] **Scenario 3:** Renders Corporate Memphis floating decorative SVGs around the video frame.
- [x] **Scenario 4:** Does NOT render manual video controls, scrubbers, or OS titlebar.
- [x] **Scenario 5:** Does NOT render the removed 3-card block.

---

# Implementation Files

- `specs/SPEC-026-product-video-showcase.md` - Specification document
- `frontend/app/components/home/ProductVideoShowcase.vue` - Video showcase component
- `frontend/app/pages/index.vue` - Replace legacy demo with showcase component
- `frontend/tests/components/home/ProductVideoShowcase.test.ts` - Showcase unit test suite
- `frontend/tests/pages/index.test.ts` - Index page test suite
