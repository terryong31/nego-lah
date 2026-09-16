---
id: SPEC-071
title: Landing Hero Repositioning — Facebook Marketplace Ghosting Hook
status: complete
priority: medium
created: 2026-09-11
tags: [frontend, landing, copy, i18n]
assigned: agent
---

# Context & Objectives

The previous landing hero headline led with *"Boleh tawar? The seller is an AI"* accompanied by a playful badge *"It holds a floor price. Good luck finding it 😜"*. While catchy, it focused on the negotiation gimmick rather than the acute pain point faced by second-hand sellers: the relentless cycle of buyers sending *"Hi, is this still available?"* on Facebook Marketplace, only to ghost and never buy.

Industry data reveals that 75%–90% of buyers who send initial *"Is this still available?"* messages on Facebook Marketplace never follow through, costing sellers hours of wasted time each week.

This change reframes the hero section:
1. **Headline Hook**: Changes the lead headline across locales to the native Facebook Marketplace automated buyer inquiry:
   - English: *"“Hi, is this still available?”"*
   - Malay: *"“Adakah ini masih tersedia?”"*
   - Chinese: *"“你好，这个还在吗？”"*
2. **Value Proposition Description (Concise)**: Cites the ~80% Facebook Marketplace ghosting statistic and highlights Nego-lah's autonomous 24/7 AI marketplace that negotiates and closes sales 24/7:
   - English: *"Up to 80% of buyers who ask “Is this still available?” on Facebook Marketplace ghost and never buy. Nego-lah features an AI-powered marketplace that negotiates and closes sales 24/7."*
   - Malay: *"Hampir 80% pembeli yang tanya “Adakah ini masih tersedia?” di Facebook Marketplace akhirnya senyap dan tak jadi beli. Nego-lah menampilkan pasaran AI yang berunding dan memuktamadkan jualan 24/7."*
   - Chinese: *"在 Facebook Marketplace 上，高达 80% 发来“你好，这个还在吗？”的买家最终都会已读不回。Nego-lah 打造全天候 24/7 自动议价并促成交易的 AI 二手市场。"*
3. **Badge Removal**: Deletes the floor price playful badge to create a cleaner, more focused hero copy hierarchy.
4. **Hero Scene Character Dialogue Bubbles**: Comic-style speech bubbles anchored to the Memphis character illustration:
   - Corporate Memphis lady asking: *"Is this still available?"* / *"Adakah ini masih tersedia?"* / *"请问这个还在吗？"*
   - AI assistant robot replying: *"Yes, it's available!"* / *"Ya, masih tersedia!"* / *"在的，还在！"*

# Acceptance Criteria

- [x] The hero headline displays the native FB marketplace inquiry with the key hook word highlighted and underlined with the Corporate Memphis wave accent (`available?”` / `tersedia?”` / `还在吗？”`).
- [x] The hero description references that up to 80% of buyers who ask the question on Facebook Marketplace ghost and never buy, and introduces the 24/7 AI marketplace that negotiates and closes sales.
- [x] The floor price badge (`UBadge` rendering `heroPs`) is removed from the hero section.
- [x] Character dialogue speech bubbles render with directional tails pointing directly to the lady and the robot.
- [x] Full trilingual parity across `en`, `ms`, and `zh` locales for dialogue text (`home.heroBuyerBubble` and `home.heroAiBubble`).
- [x] Speech bubbles scale cleanly across desktop and mobile viewports without collision or text overflow.
- [x] Automated tests in `frontend/tests/pages/index.test.ts` and `frontend/tests/components/hero/MemphisCharacters.test.ts` pass.

# Technical Design & Files Changed

- `frontend/app/locales/en.json`, `ms.json`, `zh.json`: Updated `home.heroTitle1`, `home.heroTitle2`, `home.heroBrand`, `home.heroDesc`, `home.heroBuyerBubble`, `home.heroAiBubble`.
- `frontend/app/pages/index.vue`: Removed the `UBadge` container from `#description` and standardized spacing interpolation between `heroTitle2` and `heroBrand`.
- `frontend/app/components/hero/MemphisCharacters.vue`: Added animated dialogue speech bubbles with 45-degree rotated tail pointers anchored inside the floating character container.
- `frontend/tests/pages/index.test.ts`: Updated hero copy assertions to match new text.
- `frontend/tests/components/hero/MemphisCharacters.test.ts`: Added assertions verifying the 2 speech bubbles and dialogue text rendering.
