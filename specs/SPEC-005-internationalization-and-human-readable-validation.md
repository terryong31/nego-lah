---
id: SPEC-005
title: Full-Stack Trilingual i18n, Server Metadata Sync, and End-to-End Zod Validation
status: in-progress
priority: high
created: 2026-09-04
tags: [frontend, backend, i18n, localization, validation, zod, ai-agent]
assigned: agent
---

# Context & Objectives
Nego-lah is a Malaysian second-hand marketplace with AI-powered negotiation. Malaysia is trilingual in commerce (English, Bahasa Melayu, and Chinese). This specification defines:
1. **Server-Side Persisted Language Preference & Geolocation Fallback**:
   - Unauthenticated: Detect user browser locale / country and persist in `localStorage`.
   - On Login: Sync language with user metadata on the backend (`preferred_language`). If metadata is empty, automatically save current client language to the database.
   - Authenticated: Follow user metadata; changes persist to backend and `localStorage`.
   - UI: Bottom-bar language switcher located immediately to the left of the dark/light mode toggle.
2. **End-to-End Zod Validation Across the Entire Frontend**:
   - Every user input across the entire client (Auth, Profile, Admin Items, Checkout/Shipping, Chat) validated via Zod schemas.
   - Global reactive Zod error map translating all validation codes into human-readable, conversational explanations in `en`, `ms`, and `zh`.
3. **Multilingual AI Listing Generator in `_console`**:
   - Admin item creation supports selecting listing language (`en`, `ms`, `zh`).
   - Gemini Vision AI pipeline generates titles, conditions, and markdown descriptions in the selected language.

# Acceptance Criteria
- [ ] **Language Preference Lifecycle**:
  - Unauthenticated first visit detects browser/country language and defaults to `en`, `ms`, or `zh` with `localStorage` caching.
  - Login checks user metadata `preferred_language`. If present, applies it. If absent, writes current client locale to user metadata.
  - Changing language while logged in immediately persists `preferred_language` to backend.
- [ ] **Footer Language Switcher**:
  - Placed directly to the left of `<UColorModeSelect />` in all layouts (`default.vue`, `dashboard.vue`, `chat.vue`).
- [ ] **Zod For Everything (Entire Client)**:
  - Auth: `loginSchema`, `registerSchema`, `forgotPasswordSchema`, `resetPasswordSchema`.
  - Profile: `profileInfoSchema`, `emailChangeSchema`, `passwordChangeSchema`.
  - Admin: `adminLoginSchema`, `adminItemSchema`, `adminUserBanSchema`.
  - Checkout & Shipping: `shippingSchema` (recipient, Malaysian phone number, address).
  - Chat: `chatInputSchema`.
  - Global `z.setErrorMap` renders friendly human-readable localized text for all error types.
- [ ] **Multilingual Admin Item Creation & AI Generation**:
  - `_console/items` creation modal includes target language selector (`en`, `ms`, `zh`).
  - `/analyze-image/stream` and `/analyze-image` accept `language` parameter.
  - Vision AI agent prompts produce listings in the specified target language.
- [ ] **Backend Server Endpoint**:
  - `PUT /user/{user_id}/language` updates `user_metadata.preferred_language` using service role.
- [ ] **Automated Tests**:
  - Unit tests verifying language detection, server metadata synchronization, multilingual AI prompt generation, and Zod error formatting in `en`, `ms`, `zh`.

# Technical Design & Contracts
### Backend API
- `PUT /user/{user_id}/language`
  - Headers: `Authorization: Bearer <jwt>`
  - Body: `{"language": "en" | "ms" | "zh"}`
  - Response: `{"message": "Language updated", "preferred_language": "..."}`
- `POST /admin/analyze-image/stream`
  - FormData: `images: File[]`, `language: "en" | "ms" | "zh"`

### Frontend Architecture
- `@nuxtjs/i18n` with `strategy: 'no_prefix'`.
- Locale files: `frontend/app/locales/en.json`, `ms.json`, `zh.json`.
- Composable: `useLanguage()` managing initial detection, local storage, and server sync.
- Component: `LanguageSelect.vue` placed beside `<UColorModeSelect />`.
- Schemas: `frontend/app/utils/schemas.ts` and plugin `frontend/app/plugins/zod-i18n.ts`.

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1 (Backend Language Update):** Test `PUT /user/{user_id}/language` persists language to user metadata and rejects invalid codes.
- [ ] **Scenario 2 (AI Prompt Language Tuning):** Test `image_analyzer` includes language directives for `ms`, `zh`, and `en`.
- [ ] **Scenario 3 (Zod Human-Readable Error Map):** Test Zod validation output across email, min-length, password match, and required fields in all 3 languages.
- [ ] **Scenario 4 (All Unit Tests Passing):** Full monorepo test suite passes without regressions.

# Implementation Files
- `backend/routes/user.py` - Add `PUT /{user_id}/language`
- `backend/agent/tools/image_analyzer.py` - Multilingual vision prompts
- `backend/agent/tools/listing_pipeline.py` - Pass `language` to vision analyzer
- `backend/routes/admin.py` - Accept `language` in analyze endpoints
- `backend/tests/test_user_language.py` - Test user language API
- `frontend/package.json` - `@nuxtjs/i18n`
- `frontend/nuxt.config.ts` - i18n module configuration
- `frontend/app/locales/en.json`, `ms.json`, `zh.json` - Dictionaries
- `frontend/app/composables/useLanguage.ts` - Client detection and sync composable
- `frontend/app/components/LanguageSelect.vue` - Bottom footer language switcher
- `frontend/app/utils/schemas.ts` - Universal client Zod schemas
- `frontend/app/plugins/zod-i18n.ts` - Global Zod error map
- `frontend/app/layouts/default.vue`, `dashboard.vue`, `chat.vue` - Mount switcher
- `frontend/app/components/admin/AdminItems.vue` - Language selector for item creation
- `frontend/tests/plugins/zod-i18n.test.ts` - Client validation tests
