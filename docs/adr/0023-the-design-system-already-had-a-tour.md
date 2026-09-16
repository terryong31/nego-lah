# ADR 0023: The Design System Already Had a Tour, and Its Anchor Does Not Watch the DOM

## Status
Accepted

## Context

`TODO.md` item 56 asked for "VueTour" for user onboarding. Taken literally that is `vue-tour@2.0.0`, which declares `vue: ^2.6.12` as a hard dependency — it cannot run on Nuxt 4. The obvious replacements each cost something: `shepherd.js@15` is **AGPL-3.0**, which is the wrong licence for a public repository that carries a "deploy this inside your company" pitch on its front page; `vue3-tour` bundles Vue as a direct dependency rather than a peer, risking a duplicate runtime; `driver.js` is MIT and dependency-free but ships its own visual language that would have to be re-skinned onto our tokens.

None of that was necessary. `@nuxt/ui@4.11.0` — already installed — ships `useTour`, a headless composable that re-anchors a single `UPopover` across steps. It is 102 lines. It owns the step index and resolves the anchor; the popover, the copy and the navigation are ours, which means the tour is built from the same `UPopover`, `UButton` and semantic colour tokens as the rest of the app and inherits dark mode for free.

Reading that implementation before designing against it mattered more than the licence question. `reference` is a plain `computed` that calls `document.querySelector`:

```js
const reference = computed(() => {
  if (!open.value || typeof window === "undefined") return void 0
  const target = toValue(current.value?.target)
  if (target == null) return centerAnchor
  if (typeof target === "string") { … return document.querySelector(selector) ?? void 0 }
  return target
})
```

Its reactive dependencies are `open`, `index` and whatever `toValue(step.target)` touches. **The DOM is not among them.** A step whose element is not mounted at the instant it activates resolves `undefined`, and because nothing reactive changes when the element later appears, the computed never re-evaluates. The popover floats unanchored and the tour appears to hang — with no error and no failed assertion anywhere.

For a single-page tour this never comes up. For this one it is the *default* case: the arc crosses `/items` → `/items/[id]` → `/chat` → `/orders`, the header avatar lives behind `<ClientOnly>`, and the chat's pinned item header is behind a `v-if` that only fills in once `?item_id=` resolves.

The second sharp edge is in the same file: `watch(total, v => { if (!v) open.value = false })`, plus an `index` clamped to `total`. The natural implementation — a step list computed per route — would collapse the tour to zero steps on every navigation and scramble the pointer on the way back.

## Decision

**1. Use the design system's own `useTour`; add no tour dependency.** A tour is chrome, and chrome that does not match the app it explains is worse than no tour. The pieces `useTour` omits — persistence, route awareness, an overlay — are the pieces that have to be application-specific anyway.

**2. A step's target is a getter over a revision ref, never a bare selector string.**

```ts
target: () => (revision.value, document.querySelector(`[data-tour="${name}"]`) ?? undefined)
```

Reading `revision.value` inside the getter is what enrols the DOM in the computed's dependency graph. `revision` is bumped when `router.afterEach` settles, on a bounded `requestAnimationFrame` retry, and by a `MutationObserver` held only while a step is unanchored. Passing a selector string directly — the form the documentation shows — is correct only for a tour that never leaves the page it started on.

**3. The step list is stable and unfiltered for the life of the tour.** Steps that do not apply are skipped by advancing past them, never by filtering the array, because a shrinking list clamps `index` and a list that reaches zero closes the tour outright.

**4. Anchors are declared, not inferred.** Every target carries an explicit `data-tour="<kebab>"` attribute, alongside the `data-testid` convention already used in the admin components. Selecting on Nuxt UI's generated classes would tie the tour to a theme's output, and those strings are reordered between releases. Where a component renders different DOM in different states — `ItemGrid`'s loading and loaded grids are separate nodes — the anchor goes on the stable wrapper above them.

**5. The tour points; it never acts.** It sends no message, spends no tokens and never clicks Buy Now — that handler assigns `window.location.href`, which tears the SPA down mid-tour. Where a new buyer has nothing to point at (no `PayCard` before a deal, an empty orders table), the step is viewport-centred with an illustration in the popover rather than anchored to a fiction.

**6. Completion lives in `localStorage`, not `user_metadata`.** Every other per-user preference here syncs to Supabase metadata through the backend, and this one deliberately does not. A fresh browser replaying the tour is the correct behaviour for a demo app that gets shown to people; suppressing it across devices would buy nothing and cost an endpoint, its authorization and its tests.

## Consequences

- The tour cannot outlive a full page teardown. A reload mid-tour resumes from the persisted step; a redirect out to Stripe ends it, which is why checkout is described rather than performed.
- `revision` bumping is a heuristic, not a guarantee. A target that takes longer to mount than the bounded retry allows will leave its step centred instead of anchored — degraded, not broken, and the failure is visible rather than silent.
- We are now coupled to an implementation detail of `useTour` that its documentation does not mention. If a future `@nuxt/ui` makes `reference` re-resolve on its own, the getter becomes redundant but stays correct. The late-anchor test is what will tell us.
- The installed `.d.ts` names the start option `initialStep` while the published docs say `initialIndex`. We call `start(n)` and depend on neither.
- Deleting `NegotiationDemo.vue` and `AgentAvatar.vue` in the same change removes a duplicate `id="how-it-works"` and a set of locale keys the i18n coverage test could not see, because it matches only literal `$t('…')` calls and those keys were reached dynamically.
