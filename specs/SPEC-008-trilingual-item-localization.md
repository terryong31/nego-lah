---
id: SPEC-008
title: Trilingual Item Localization, Determinate Upload Progress, and Modal Polish
status: in-progress
priority: high
created: 2026-09-04
tags: [frontend, backend, i18n, localization, ai-vision, supabase, admin]
assigned: agent
---

# Context & Objectives
Nego-lah is a Malaysian marketplace operating across English (`en`), Bahasa Melayu (`ms`), and Chinese (`zh`). Previously, multilingual listing generation concatenated all languages into a single markdown description. This specification defines:
1. **True Trilingual Item Model**:
   - `public.items` stores a `translations` JSONB column holding `{ [locale]: { name, description, condition } }`.
   - The top-level `name`, `description`, `condition` act as the default fallback.
2. **Structured AI Vision Generation**:
   - Gemini Vision AI generates clean, distinct translations for `en`, `ms`, and `zh` without embedding markdown headers in a single body.
3. **Reactive Storefront Internationalization**:
   - When a user changes the language using the site-wide language switcher, `ItemCard` and `/items/[id]` reactively display the localized name, condition, and markdown description.
4. **Admin Upload UX Polish**:
   - Determinate progress bar showing true percentage (`0% - 100%`) without looping carousel animation.
   - Removal of the "Auto-filled by AI" alert callout.
   - Multi-tab language editor (**English**, **Bahasa Melayu**, **中文**) in the item modal.

# Acceptance Criteria
- [ ] **Database Migration**:
  - `public.items` includes `translations jsonb DEFAULT '{}'::jsonb`.
- [ ] **Determinate Progress Bar**:
  - `<UProgress :model-value="progress" :max="100" />` shows actual numerical completion without infinite circling.
- [ ] **Alert Callout Removed**:
  - `<UAlert title="Auto-filled by AI" ... />` is removed from the admin modal.
- [ ] **Trilingual AI Output**:
  - Vision analyzer returns a structured `translations` map for `en`, `ms`, and `zh`.
- [ ] **Admin Item Creation & Edit**:
  - Form provides language tabs (`en`, `ms`, `zh`) allowing inspection and modification of each language.
  - Submits `translations` to `POST /admin/items` and `PUT /admin/items/{id}`.
- [ ] **Storefront Reactive Switching**:
  - `ItemCard` and `/items/[id]` display `item.translations?.[locale]?.name || item.name` and corresponding description/condition, updating instantaneously when `locale` changes.
- [ ] **Full Automated Test Coverage**:
  - Vitest tests for `AdminItems.vue`, `ItemCard.vue`, `items/[id].vue`, and backend pytest tests pass with zero regressions.

# API Contracts & Data Shapes
### Translations Schema
```json
{
  "en": { "name": "Apple AirPods Max", "description": "...", "condition": "Like New" },
  "ms": { "name": "Fon Kepala Apple AirPods Max", "description": "...", "condition": "Seperti Baru" },
  "zh": { "name": "Apple AirPods Max 头戴式耳机", "description": "...", "condition": "九成新" }
}
```

### Backend Endpoints
- `POST /admin/items`: Form fields `name`, `description`, `condition`, `price`, `images`, optional `min_price`, optional `translations` (JSON string).
- `PUT /admin/items/{item_id}`: JSON body includes optional `translations` dict.
- `GET /items`, `GET /items/{id}`: Returns `translations` JSON object in payload.
