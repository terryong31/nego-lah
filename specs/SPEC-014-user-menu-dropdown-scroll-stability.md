---
id: SPEC-014
title: User Menu Dropdown Scroll Stability
status: complete
priority: medium
created: 2026-09-05
tags: [frontend, nuxt, navigation, header, ui]
assigned: agent
---

# Context & Objectives
When a user scrolls down on any page (e.g., the landing page or item list) and clicks the user profile dropdown menu in the sticky `<AppHeader>`, the entire navigation bar suddenly disappears / goes missing.

### Root Cause
Nuxt UI's `<UDropdownMenu>` (backed by Reka UI's `DropdownMenuRoot`) defaults to `modal: true`. In modal mode, Reka UI enables `disable-outside-scroll`, invoking `useBodyScrollLock` which applies `overflow: hidden` to `document.body`. When `document.body` is assigned `overflow: hidden`, any sticky descendant element (`position: sticky; top: 0` on `<UHeader>`) loses its viewport scroll context and resets relative to `body` with `scrollTop: 0`. As a result, the sticky header instantly jumps to the very top of the page, out of view for scrolled users.

The objective is to configure the user menu `<UDropdownMenu>` in `<AppHeader>` with `:modal="false"` (and optimal content alignment), preventing body scroll-locking and ensuring the top navigation remains securely anchored at the top of the viewport when opened while scrolled.

# Acceptance Criteria
- [x] Set `:modal="false"` on the user avatar `<UDropdownMenu>` in `AppHeader.vue` so it behaves as a non-modal popup without scroll-locking `document.body`.
- [x] Configure dropdown content alignment (`:content="{ align: 'end' }"`) so the menu aligns cleanly with the user trigger on mobile and desktop without viewport edge overflow.
- [x] Automated tests assert that `<UDropdownMenu>` in `AppHeader.vue` receives `modal: false`.
- [x] All existing `AppHeader` and layout test suites pass.

# Technical Design & Contracts
In `frontend/app/components/AppHeader.vue`:
```vue
<UDropdownMenu
  :modal="false"
  :items="dropdownItems"
  :content="{ align: 'end' }"
>
```

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** Mount `AppHeader` with an authenticated user and assert that `UDropdownMenu` has the `modal` prop set to `false`.
- [x] **Scenario 2:** Verify that all dropdown items, navigation actions, and logout behaviors remain intact.

# Implementation Files
- `frontend/app/components/AppHeader.vue` - Set `:modal="false"` and `:content="{ align: 'end' }"` on `<UDropdownMenu>`.
- `frontend/tests/components/AppHeader.test.ts` - Add test asserting non-modal dropdown configuration.
