---
id: SPEC-075
title: Three-Step Pipeline Walkthrough (Upload → Nego → Delivery)
status: complete
priority: low
created: 2026-09-12
tags: [frontend, landing, i18n]
assigned: agent
---

# Context & Objectives
The SPEC-069 "How it works" walkthrough scrubs through six stages (Upload,
Memory, Nego, Deal, Paid, Delivery). Six words is more ceremony than story:
the middle steps (Memory, Deal, Paid) are implementation details a visitor
does not need, and the scroll pinned section feels long for what it teaches.
Shorten the walkthrough to three stages — **Upload, Nego, Delivery** — keeping
the existing stage ids so the already-uploaded R2 recordings and posters
(`listing.*`, `haggle.*`, `delivery.*`) keep working untouched.

# Acceptance Criteria
- [x] The stepper shows exactly three items: Upload, Nego, Delivery (and their
      ms/zh translations).
- [x] The dropped stages (`knowledge`, `checkout`, `order`) leave the component
      AND their i18n keys leave all three locale files (no dead keys).
- [x] Stage ids stay `listing` / `haggle` / `delivery`, so video URLs are
      unchanged.
- [x] The pinned track stays ~one viewport of scroll per step (derived from the
      stage count, not a hardcoded `600vh`).
- [x] Existing behaviours keep their tests: click-to-jump, lazy `<source>`
      loading, keep-visited-videos, placeholder-when-no-frames.

# Technical Design & Contracts
- `STAGES` shrinks to listing / haggle / delivery. Everything derived from
  `STAGES.length` (scroll slicing, `travelled`, `activeStep`) adapts on its own.
- Track height becomes a bound style: `STAGES.length * 100vh` when pinned
  (300vh today), so the per-step scroll feel can never drift from the list.
- `home.pipeline.items.{knowledge,checkout,order}` removed from `en.json`,
  `ms.json`, `zh.json`.
- Recordings for dropped steps stay in the R2 bucket unreferenced; `media:sync`
  is directory-based and needs no change.

# Test-Driven Development (TDD) Scenarios
- [x] UStepper receives exactly three items titled Upload / Nego / Delivery.
- [x] Selecting the last step (index 2) shows the `delivery.jpg` poster.
- [x] The keep-visited test drives haggle at its new index (1).
- [x] Exactly three posters render; first source is still `listing.mp4`.
- [x] The index page renders the three labels and none of the dropped ones.

# Implementation Files
- `frontend/app/components/home/AgentPipeline.vue` - 3-stage list, derived track height
- `frontend/app/locales/en.json` / `ms.json` / `zh.json` - drop dead keys
- `frontend/tests/components/home/AgentPipeline.test.ts` - updated expectations
- `frontend/tests/pages/index.test.ts` - updated label list
