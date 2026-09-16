---
id: SPEC-025
title: Motion for Vue Negotiation Demo Upgrade
status: abandoned
superseded_by: SPEC-026
priority: medium
created: 2026-09-06
tags: [frontend, animation, motion, ux]
assigned: agent
---

# Context & Objectives

The landing page demo component (`frontend/app/components/home/NegotiationDemo.vue`) illustrates Nego-Lah's core value proposition: an autonomous AI agent negotiating with a buyer over a pre-loved item (Sony WH-1000XM4).

### Current Implementation Bottlenecks:
1. **Manual Scroll Polling**: Uses raw `window.addEventListener('scroll')`, `requestAnimationFrame`, and manual `getBoundingClientRect()` calculations to scrub the 300vh pinned track.
2. **Linear CSS Transitions**: Dialogue bubbles toggle Tailwind classes (`transition-all duration-500 ease-out`, `opacity-0 translate-y-6`). The animations feel mechanical and lack physical weight or spring inertia.
3. **Abrupt Step Indicators**: Step numerals (`01`, `02`, `03`) abruptly swap `-webkit-text-stroke-color` with discrete threshold triggers, without fluid indicator transitions.

### Objectives:
Upgrade the component to use **Motion for Vue** (`motion-v` / [motion.dev/docs/vue](https://motion.dev/docs/vue)), bringing:
- Physics-based spring animations for chat bubble reveals and tilts (`stiffness`, `damping`, `mass`).
- Hardware-accelerated, spring-smoothed scroll progress via `useScroll` and `useSpring`.
- Shared layout animation (`layoutId`) for step tab indicators (01 Offer, 02 Counter, 03 Deal).
- Micro-interactions (hover/tap spring gestures) on interactive elements.
- Strict preservation of the editorial 12-column grid, Corporate Memphis background motifs, i18n locales, and Cloudflare Pages SPA (`ssr: false`) architecture.

---

# Acceptance Criteria

### 1. Dependency & Module Setup
- [ ] Install `motion-v` (^2.4.2) in `frontend/package.json` using `bun add motion-v`.
- [ ] Register `motion-v/nuxt` in `frontend/nuxt.config.ts` modules.
- [ ] As per Motion.dev docs, explicitly import `{ motion }` from `motion-v` in `NegotiationDemo.vue` (since `<motion.*>` dynamic components require explicit imports).

### 2. Scroll-Linked Scrubbing with Spring Smoothing
- [ ] Replace manual `requestAnimationFrame` + `getBoundingClientRect` with Motion's `useScroll`:
  ```ts
  const track = useTemplateRef<HTMLElement>('track')
  const { scrollYProgress } = useScroll({
    target: track,
    offset: ['start start', 'end end']
  })
  const smoothProgress = useSpring(scrollYProgress, { stiffness: 100, damping: 30, restDelta: 0.001 })
  ```
- [ ] Derive active step and revealed bubbles from `smoothProgress` via `useMotionValueEvent` or reactive computed mapping, preserving the lead-in (`0.01`) and settled (`0.80`) ranges.

### 3. Spring-Physics Dialogue Bubble Reveals
- [ ] Wrap dialogue bubbles in `<motion.div>` with spring entrance physics:
  - Initial state: `{ opacity: 0, y: 24, scale: 0.92, rotate: 0 }`
  - Animated state (when revealed): `{ opacity: 1, y: 0, scale: 1, rotate: beat.tilt }`
  - Spring transition: `{ type: 'spring', stiffness: 350, damping: 26, mass: 0.8 }`
- [ ] Preserve dialogue role stylings:
  - Agent: `bg-elevated border border-default text-default rounded-[1.75rem] rounded-bl-lg` with `HomeAgentAvatar`.
  - Buyer: `bg-primary text-inverted rounded-[1.75rem] rounded-br-lg shadow-primary/20` with user avatar badge.
- [ ] Preserve price inline extraction (`RM\s?\d[\d,]*`) and Memphis wave SVG underlines.

### 4. Interactive Step Navigation Strip
- [ ] Step buttons (`01 Offer`, `02 Counter`, `03 Deal`) support clicking to smoothly scroll to the target slice of the track.
- [ ] Active step indicator features a shared layout animation pill/underline using `<motion.span layoutId="active-step-indicator" />` or spring color transition.
- [ ] Step buttons have tactile micro-gestures: `:whileHover="{ scale: 1.02 }"` and `:whileTap="{ scale: 0.98 }"`.

### 5. Accessibility & Performance Guardrails
- [ ] Gracefully handle `prefers-reduced-motion` using `useReducedMotion()` from `motion-v`:
  - When active, collapse the track (`h-auto` instead of `h-[300vh]`) and render all 5 dialogue bubbles immediately in their settled state with transitions disabled.
- [ ] Mobile viewports (< 640px): Ensure the single-active-step text collapse and compact dialogue bubble padding remain stationary on short screens without overflow clipping.
- [ ] Zero SSR or browser-global crashes during Vitest execution (guard DOM refs when testing with `happy-dom`).

---

# Technical Design & Contracts

### Component Contract (`frontend/app/components/home/NegotiationDemo.vue`)

```vue
<script setup lang="ts">
import { motion, useScroll, useSpring, useMotionValueEvent, useReducedMotion } from 'motion-v'

type Role = 'agent' | 'buyer'

interface Beat {
  key: string
  role: Role
  place: string
  size: string
  tilt: number
  pull: string
}

const BEATS: Beat[] = [
  { key: 'm1', role: 'agent', place: 'lg:col-start-1 lg:col-end-8', size: 'text-base sm:text-lg', tilt: -0.8, pull: '' },
  { key: 'm2', role: 'buyer', place: 'lg:col-start-7 lg:col-end-13', size: 'text-base sm:text-lg', tilt: 1.2, pull: 'lg:-mt-2' },
  { key: 'm3', role: 'agent', place: 'lg:col-start-2 lg:col-end-10', size: 'text-lg sm:text-xl', tilt: -0.5, pull: '' },
  { key: 'm4', role: 'buyer', place: 'lg:col-start-8 lg:col-end-13', size: 'text-xl sm:text-2xl lg:text-3xl', tilt: 1.8, pull: 'lg:-mt-3' },
  { key: 'm5', role: 'agent', place: 'lg:col-start-1 lg:col-end-8', size: 'text-base sm:text-lg', tilt: -1.1, pull: 'lg:-mt-5' }
]

const STEPS = [
  { id: 'offer', upTo: 2 },
  { id: 'counter', upTo: 3 },
  { id: 'deal', upTo: 5 }
] as const

const LEAD_IN = 0.01
const SETTLED = 0.80

const track = useTemplateRef<HTMLElement>('track')
const shouldReduceMotion = useReducedMotion()

// Scroll tracking via Motion
const { scrollYProgress } = useScroll({
  target: track,
  offset: ['start start', 'end end']
})

const smoothProgress = useSpring(scrollYProgress, {
  stiffness: 120,
  damping: 28,
  restDelta: 0.001
})

const rawProgress = ref(0)
useMotionValueEvent(smoothProgress, 'change', (latest) => {
  rawProgress.value = latest
})

const revealed = computed(() => {
  if (shouldReduceMotion.value) return BEATS.length
  const p = (rawProgress.value - LEAD_IN) / (SETTLED - LEAD_IN)
  return Math.max(0, Math.min(BEATS.length, Math.ceil(p * BEATS.length)))
})

const activeStep = computed(() => {
  const index = STEPS.findIndex(s => revealed.value <= s.upTo)
  return index === -1 ? STEPS.length - 1 : index
})
</script>
```

### Spring Transition Configurations

```ts
export const BUBBLE_SPRING = {
  type: 'spring',
  stiffness: 350,
  damping: 25,
  mass: 0.8
}

export const STEP_PILL_SPRING = {
  type: 'spring',
  stiffness: 400,
  damping: 32
}
```

---

# Test-Driven Development (TDD) Scenarios

Create `frontend/tests/components/home/NegotiationDemo.test.ts`:

- [ ] **Scenario 1: Component Mounting & Semantic Structure**
  - Mount component via `mountSuspended(NegotiationDemo)`.
  - Assert `#how-it-works` section exists.
  - Assert 3 step buttons (`01`, `02`, `03`) exist and contain titles and descriptions.
  - Assert headline contains lead, accent with Memphis underline wave, and tail.

- [ ] **Scenario 2: Dialogue Beats & Avatar Rendering**
  - Verify all 5 dialogue beat keys (`home.dialog.m1` through `m5`) are rendered.
  - Verify agent beats render `<HomeAgentAvatar>` and buyer beats render the user circle badge.
  - Verify price tags (`RM320`, `RM240`, `RM280`) are isolated with underline SVG.

- [ ] **Scenario 3: Step Navigation Interaction**
  - Click on step 2 (`02 Counter`) button.
  - Assert `window.scrollTo` or target step calculation is invoked with expected offsets.
  - Verify `activeStep` reactive state reflects step index.

- [ ] **Scenario 4: Reduced Motion Mode**
  - Mock `prefers-reduced-motion: reduce` or `useReducedMotion() => ref(true)`.
  - Assert all 5 dialogue beats are rendered immediately.
  - Assert the scroll track does not apply the tall `h-[300vh]` class.

---

# Implementation Files

- `frontend/package.json` - Add `motion-v: ^2.4.2`
- `frontend/nuxt.config.ts` - Register `'motion-v/nuxt'` in `modules`
- `frontend/app/components/home/NegotiationDemo.vue` - Replace manual scroll/CSS transitions with `motion-v`
- `frontend/tests/components/home/NegotiationDemo.test.ts` - Vitest test suite asserting functionality and accessibility

---

# Execution Checklist for Implementing Agent

1. **Install Dependencies:**
   ```bash
   cd frontend && bun add motion-v
   ```
2. **Register Module:**
   In `frontend/nuxt.config.ts`, add `'motion-v/nuxt'` to the `modules` array.
3. **Write Tests First (Red):**
   Create `frontend/tests/components/home/NegotiationDemo.test.ts` and run:
   ```bash
   mise run test:frontend
   ```
4. **Implement Component (Green):**
   Update `frontend/app/components/home/NegotiationDemo.vue` with `motion-v` springs and scroll tracking.
5. **Verify Quality (Refactor):**
   ```bash
   mise run test:frontend
   mise run typecheck
   mise run lint
   ```
