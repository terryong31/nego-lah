---
id: SPEC-013
title: Branded Chat Work-Process Indicator
status: complete
priority: medium
created: 2026-09-05
tags: [frontend, chat, nuxt-ui, branding, i18n, motion]
assigned: agent
---

# Context & Objectives
The chat "agent is working" indicator used Nuxt UI's stock spinner and a hardcoded
English "Thinking…". Replace both: the spinner becomes the Nego-Lah mark doing a
small hop with a 3D flip (the SPA loading screen's motion at icon scale), and the
label becomes the trilingual "Cooking…" line.

# Acceptance Criteria
- [x] The mark ships as a monochrome `currentColor` SVG, consumed as a normal
      icon name `i-nego-mark` via a @nuxt/icon custom collection — NOT as a
      hand-rolled SVG in a component slot (`UChatTool` exposes no `leading` slot;
      its icon is prop-driven).
- [x] The collection is inlined into the client bundle (`includeCustomCollections`)
      because `ssr: false` leaves no icon server in production.
- [x] The indicator drops the `loading` prop. `loading` resolves
      `appConfig.ui.icons.loading` and stamps `animate-spin` on `leadingIcon`
      (see `.nuxt/ui/chat-tool.ts`), which would clobber both the mark and its hop.
- [x] Icon colour is `text-default`; the hop is applied through the documented
      `ui.leadingIcon` slot override.
- [x] Jump stays subtle — max 3px translate at `size-4` — and is disabled under
      `prefers-reduced-motion`.
- [x] Seller-typing (human takeover) keeps its own `i-lucide-store` icon, unanimated.
- [x] `aiStatusText` holds only the backend's `[[STATUS:…]]` text and resets to
      empty, so the idle label comes from the translated `chat.thinking` key
      rather than a hardcoded English string.

# Technical Design & Contracts
- **Icon:** `frontend/app/assets/icons/mark.svg` → `nego:mark` → `i-nego-mark`.
  Stroke-only silhouette (bubble + N); the gradient, eyelet and sparkle from
  `AppLogo.vue` are dropped as they turn to mud below ~24px, and the N is
  enlarged slightly for optical sizing.
- **Motion:** `.animate-brand-hop` in `main.css`. One keyframe drives translate,
  squash-stretch and `rotateY` together so the 360° flip stays locked to the
  airborne phase and always lands facing front — mirrors `loaderJump`/`loaderSpin`
  in `spa-loading-template.html`, scaled from 56px to 3px.
- **Label:** `chat.thinking` → `Cooking…` / `Sedang masak…` / `正在烹煮…`.
  The backend's unmapped-tool fallback in `agent/bot.py` matches (`Cooking...`);
  its other statuses stay English-only (pre-existing, unchanged).

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** `mark.svg` is `currentColor`-only, carries no hex/gradient,
      and has no `width`/`height` so `size-*` governs it (`brandMarkIcon.test.ts`).
- [x] **Scenario 2:** `nuxt.config.ts` registers the `nego` collection and sets
      `includeCustomCollections: true`.
- [x] **Scenario 3:** `brand-hop` exists, uses `rotateY`, hops ≤4px, and is
      nulled under `prefers-reduced-motion`.
- [x] **Scenario 4:** The indicator renders with `loading === false`,
      `icon === 'i-nego-mark'`, and `ui.leadingIcon` carrying `animate-brand-hop`
      + `text-default` (`tests/pages/chat.test.ts`).
- [x] **Scenario 5:** Seller-typing renders `i-lucide-store` with no hop.
- [x] **Scenario 6:** `aiStatusText` starts empty and resets to empty on
      `submitted`.

# Implementation Files
- `frontend/app/assets/icons/mark.svg`
- `frontend/nuxt.config.ts`
- `frontend/app/assets/css/main.css`
- `frontend/app/pages/chat.vue`
- `frontend/app/locales/{en,ms,zh}.json`
- `backend/agent/bot.py`
