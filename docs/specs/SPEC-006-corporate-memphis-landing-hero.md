---
id: SPEC-006
title: Corporate Memphis Landing Page Hero Refactor
status: complete
priority: high
created: 2026-09-04
tags: [frontend, design, ui, animation]
assigned: agent
---

# Context & Objectives
Refactor the landing page hero section in `frontend/app/pages/index.vue` to adopt a bold, modern **Corporate Memphis / Alegria** visual identity, featuring an enlarged 2D animated vector scene (Terry with his Fender Stratocaster electric guitar and his AI bot companion with a swinging price tag paddle), ambient retro-modern Memphis geometry, and a punchy, brand-centric headline ("Find something you like? Come Nego-lah").

# Acceptance Criteria
- [x] **Corporate Memphis Aesthetic**: Incorporate stylized flat geometric human and mascot figures (Terry with Fender Strat, AI negotiation bot with swinging price tag paddle) and Memphis motifs (floating squiggles, confetti dots, rotated pills, starbursts).
- [x] **2D Animated Elements**: Smooth 2D CSS/SVG animations (`animate-memphis-float`, `animate-memphis-wobble`, `animate-memphis-spin-slow`) with accessibility support for `prefers-reduced-motion`.
- [x] **Enlarged 2D Illustration Showcase**: Expanded the 2D animated Corporate Memphis character scene to be the prominent focal point of the hero section.
- [x] **Brand Headline**: Replaced the introductory heading with the catchy marketplace slogan: *"Find something you like? Come Nego-lah"* with stylized highlight on *"Nego-lah"*.
- [x] **Removed Clutter**: Removed the top pill (`AI-Powered Secondhand Marketplace`), the `DEAL! 🤝` overlay pill, the category perk tags (`Fender & Guitars`, `Gadgets & Gear`, `Live AI Haggling`), and the chat demo card.
- [x] **Design System & Dark/Light Mode**: Full visual fidelity across both light mode and dark mode using Tailwind CSS v4 and Nuxt UI color tokens.
- [x] **Internationalization**: Full multilingual support across `en`, `zh`, and `ms`.
- [x] **Test & Quality Suite**: All Vitest test suites, TypeScript checks, and ESLint pass with 0 errors.

# Technical Design & Contracts
- **Components**:
  - `frontend/app/components/hero/MemphisCharacters.vue`: Scaled vector SVG character scene (Terry with Fender Strat + AI Bot) with 2D animated limbs, blinking eyes, and swinging price tag.
  - `frontend/app/components/hero/MemphisDecors.vue`: Floating geometric background/foreground Memphis elements.
  - `frontend/app/pages/index.vue`: Clean, spacious hero layout pairing copy & CTA with the large 2D animated Memphis scene.
- **Translations (`locales/*.json`)**:
  - `home.heroTitle1`: "Find something you like?"
  - `home.heroTitle2`: "Come"
  - `home.heroBrand`: "Nego-lah"

# Implementation Files
- `frontend/app/locales/en.json` - Localization strings (English)
- `frontend/app/locales/zh.json` - Localization strings (Chinese)
- `frontend/app/locales/ms.json` - Localization strings (Malay)
- `frontend/app/assets/css/main.css` - Custom Memphis animation keyframes
- `frontend/app/components/hero/MemphisCharacters.vue` - 2D animated Memphis characters
- `frontend/app/components/hero/MemphisDecors.vue` - Floating geometric accents
- `frontend/app/pages/index.vue` - Hero template refactor
- `frontend/tests/pages/index.test.ts` - Vitest test suite assertions
