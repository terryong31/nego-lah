---
id: SPEC-072
title: Mobile Header Avatar-Only User Dropdown
status: complete
priority: medium
created: 2026-09-11
tags: [frontend, navigation, responsive]
assigned: agent
---

# Context & Objectives
In mobile viewports, the user dropdown menu in `AppHeader.vue` displays `UUser` with the full greeting (`Hello, <display_name|email>`) and chevron icon. This consumes excessive horizontal screen real estate on mobile devices. On mobile viewports (< `sm`), the dropdown trigger should display `UAvatar` only, while preserving the full greeting and chevron on desktop viewports (`sm` and above).

# Acceptance Criteria
- [x] Mobile viewports render `<UAvatar>` only for the user dropdown trigger (greeting text and chevron are hidden).
- [x] Desktop viewports (`sm:` breakpoint and up) continue rendering the full `UUser` greeting and chevron icon.
- [x] The mobile `UAvatar` correctly receives `src="resolveAvatarUrl(user)"`, `alt="user.email || ''"`, and `loading="lazy"`.
- [x] The `UChip` unread badge and `data-tour="header-user"` trigger attributes remain functional across all viewports.
- [x] Automated tests in `frontend/tests/components/AppHeader.test.ts` assert the mobile `UAvatar` presence and responsive container styling.

# Technical Design & Contracts
- Modify `frontend/app/components/AppHeader.vue`:
  - Inside `<UDropdownMenu>` -> `<UChip>` -> `<div class="flex items-center gap-1.5 cursor-pointer">`:
    - Add `<UAvatar class="sm:hidden" :src="resolveAvatarUrl(user)" :alt="user.email || ''" loading="lazy" />`.
    - Wrap `<UUser>` and `<UIcon name="i-lucide-chevron-down" ... />` inside `<div class="hidden sm:flex items-center gap-1.5">`.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** Mount `AppHeader` for a logged-in user and verify that a `UAvatar` with `sm:hidden` exists and has `src` populated from `resolveAvatarUrl`.
- [x] **Scenario 2:** Verify that the desktop container with `hidden sm:flex` contains `UUser` and the chevron icon.

# Implementation Files
- `frontend/app/components/AppHeader.vue` - Add mobile `UAvatar` trigger and responsive desktop container.
- `frontend/tests/components/AppHeader.test.ts` - Unit tests for responsive user menu triggers.
