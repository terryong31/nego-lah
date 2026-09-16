---
id: SPEC-073
title: Pipeline Recording Coming Soon UEmpty Component
status: complete
priority: low
created: 2026-09-11
tags: [frontend, landing, design-system]
assigned: agent
---

# Context & Objectives
In `frontend/app/components/home/AgentPipeline.vue`, the placeholder state displayed when a stage recording has not yet loaded ("Recording coming soon") was previously implemented using ad-hoc `div` and paragraph elements. To align with the Nuxt UI design system, replace this custom markup with the official `<UEmpty>` component with a primary-colored icon avatar and subtle styling.

# Acceptance Criteria
- [x] Replace custom placeholder DOM in `AgentPipeline.vue` with `<UEmpty>` when `!ready.has(active.id)`.
- [x] Render the active stage icon via `<UEmpty :icon="active.icon" :avatar="{ color: 'primary' }" ... />`.
- [x] Display the localized "Recording coming soon" string (`home.pipeline.soon`) via `UEmpty`.
- [x] Apply `variant="naked"` and `class="absolute inset-0"` so `UEmpty` fits seamlessly within the video frame without extra outlines.
- [x] Update and verify tests in `frontend/tests/components/home/AgentPipeline.test.ts` to assert `<UEmpty>` rendering and disappearance on `loadeddata`.

# Technical Design & Contracts
- In `frontend/app/components/home/AgentPipeline.vue`:
  - Replace `<div v-if="!ready.has(active.id)" ...>` with:
    ```vue
    <UEmpty
      v-if="!ready.has(active.id)"
      variant="naked"
      size="lg"
      :icon="active.icon"
      :avatar="{ color: 'primary' }"
      :description="$t('home.pipeline.soon')"
      :ui="{ description: 'font-medium' }"
      class="absolute inset-0"
    />
    ```

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** Mount `AgentPipeline` and verify that `wrapper.findComponent({ name: 'UEmpty' })` exists and contains "Recording coming soon".
- [x] **Scenario 2:** Trigger `loadeddata` on the video element and assert `wrapper.findComponent({ name: 'UEmpty' }).exists()` becomes false.

# Implementation Files
- `frontend/app/components/home/AgentPipeline.vue` - Integrate `UEmpty` for the recording placeholder.
- `frontend/tests/components/home/AgentPipeline.test.ts` - Assert `UEmpty` component lifecycle.
