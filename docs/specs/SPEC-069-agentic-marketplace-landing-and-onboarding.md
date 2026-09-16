---
id: SPEC-069
title: The Front Page Sells A Shop, Not The Machine Behind It
status: complete
priority: medium
created: 2026-09-11
tags: [frontend, landing, onboarding, i18n, orders]
assigned: agent
---

# Context & Objectives

`/` sells Terry's stuff in the first person — *"Find something you like?"*, *"Browse my stuff"*, *"Three things **I** won't budge on"*, *"**I** photograph the scratches"*. A stranger reading it learns there is a second-hand shop. They do not learn that the seller is an autonomous agent, that it haggles in ringgit above a floor price it never reveals, that agreeing emits a Stripe link, or that a J&T parcel gets tracked afterwards. The most interesting thing about this system is invisible on its front page, and the single CTA drops the reader straight into a grid of guitars.

Signing in explains nothing either. `AppHeader` hides its nav toggle entirely (`AppHeader.vue:69`), `/items` is linked from exactly one button on the landing page, and `/orders` is reachable only from inside the avatar dropdown.

Closes `TODO.md` **10** (landing page), **22** (design refactor) and **56** (onboarding tour).

Three moves: reframe `/` as an illustration of an agentic marketplace in Malaysian context; point its CTA at login; and walk a newly signed-in buyer through listing → negotiate → checkout → track with a guided tour.

The page ends up shorter than it started. The standalone video showcase, the house rules and a closing CTA band were all cut: the walkthrough now carries the video, and one call to action in the hero is enough when the whole page is one argument for it.

**No tour dependency is needed.** `vue-tour@2.0.0` requires `vue@^2.6.12` and cannot run on Nuxt 4; `shepherd.js` is AGPL-3.0, wrong for a public repo carrying a B2B pitch. `@nuxt/ui@4.11.0` already ships a headless `useTour` — it owns step index and anchor resolution and hands back `reference` for `<UPopover :reference>`. See ADR 0023.

# Acceptance Criteria

- [x] `/`'s copy describes the platform, not one seller; no first-person shopkeeper voice remains.
- [x] A new `AgentPipeline` section — "How it works" — walks six steps from upload to doorstep, one screen recording each, scrubbed by a pinned scroll track on desktop and tappable everywhere else.
- [x] The section holds one heading, one recording and six one-word steps. Nothing repeats what the video already shows.
- [x] The hero CTA sends a signed-out reader to `/login?redirect=/items`; a signed-in one goes straight to `/items`.
- [x] A 13-step tour auto-starts once on `/items` after sign-in and is replayable from the user menu.
- [x] The tour survives route changes across `/items` → `/items/[id]` → `/chat` → `/orders` without stalling on an unmounted anchor.
- [x] The tour never sends a message, never spends tokens, and never triggers checkout on the user's behalf.
- [x] `/orders` shows courier and a tracking link for shipped orders.
- [x] `tour.*` and the rewritten `home.*` exist at full parity in en, ms and zh.

# Technical Design & Contracts

**`useTour` has three gaps that dictate the design** (`node_modules/@nuxt/ui/dist/runtime/composables/useTour.js`):

1. `reference` is a plain `computed` calling `document.querySelector` (`:25-42`). Its reactive deps are `open`, `index` and `toValue(step.target)` — **not the DOM**. An anchor that is not mounted the instant a step activates resolves `undefined` and *never retries*: mid route transition, behind `v-if`, inside `<ClientOnly>`. Across four routes that is the default outcome, not an edge case. Every step's target is therefore a getter that reads a revision ref, which is what enrols the DOM in that computed's dependency graph:
   `target: () => { void revision.value; return anchorEl(step.anchor) ?? null }`
   `revision` is bumped when a step activates, on a bounded `setTimeout` retry (20 × 50ms), and by a `MutationObserver` held only while a step is unanchored.

   A related detail found while building it: `useTour` tests `target == null`, **loose**, so `undefined` centres the popover exactly as `null` does. There is no third "still looking" value a step can return — an anchor that has not arrived yet is centred, and re-points when it does. `isSettling` is exported so the renderer can tell that apart from a step that is centred by design.
2. `watch(total)` force-closes the tour at zero steps and `index` is clamped to `total` (`:8-14, 78-82`). The step list must be **stable and unfiltered** — skip a step by advancing past it, never by filtering reactively.
3. No persistence, no route awareness, no overlay. Ours to build.

The published docs name the option `initialIndex`; the installed `.d.ts` and implementation say `initialStep`. Sidestep it — call `start(n)`.

**New:** `app/composables/useOnboardingTour.ts` (step registry, route driving, anchor re-resolution, persistence) and `app/components/tour/AppTour.vue` (`<UPopover :dismissible="false">` with title, body, `n / total`, Back/Next/Skip), mounted once in `app/app.vue` inside `<UApp>` so it survives the `default` → `chat` layout switch.

**Anchors:** no buyer-facing element has a stable `id` or `data-*` today. Add `data-tour="<kebab>"`, matching the `data-testid` convention already used in admin components. On `ItemGrid.vue` the anchor goes on the outer wrapper (`:19`) — the loading and loaded grids are different DOM nodes.

**Buy Now is never in the click path.** `handleBuyNow` does `window.location.href = checkout_url` (`items/[id].vue:93`, `chat.vue:653`), which tears down the SPA. Steps 9 and 12 use `target: null` (viewport-centred) because a new buyer has no `ChatPayCard` in the DOM and an empty orders table; step 9 renders a static PayCard illustration inside the popover instead.

**Persistence:** `localStorage['nego-lah-tour-v1']`, guarded as in `useLanguage.ts:91`. Deliberately not `user_metadata` — a fresh browser replaying the tour is correct for a demo app, and it keeps the backend out of this.

**Orders contract.** `orders` already carries `courier`, `tracking_number`, `tracking_url`, `shipped_at` (migration `20260910000000`), filled by the admin console, but `GET /payment/orders/user/{user_id}` never projects them (`payment.py:186-196`) — so a buyer's only tracking channel is email or asking the agent. Add the four fields to the response, deriving the URL via `resolve_tracking_url` and the display name via `normalise_courier` (`domains/catalog/shipping.py:67,81`) when `tracking_url` is null. Buyer scoping through `get_user_id_from_body_or_token` is unchanged.

**The walkthrough.** `home/AgentPipeline.vue` is a pinned scroll track — the outer element is taller than the screen while the content inside sticks, so scrolling advances the step instead of moving the page. Roughly one viewport of scroll per step.

It pins at `--ui-header-height`, not at `0`: `UHeader` is itself sticky, so a section pinned to the top of the viewport slides underneath it. The heading sits above the track rather than inside the pin — holding it on screen for six viewports of scrolling cost the recording most of a hundred pixels for a line nobody is still reading by step four.

**The steps are `UStepper`.** Three earlier drafts hand-rolled the indicator — mono labels over a hairline spine, six per-step accent colours, numbered circles on a chunky rail, a sliding underline — and every one was a worse version of a component already installed. `linear: false`, because this is a walkthrough and not a wizard: every step is reachable from every other, and selecting one scrolls the track to its slice.

Each item carries **one word**. A horizontal stepper gives each item about 150px; a sentence there wraps to three ragged lines and collides with its neighbours. There is no subtitle under the heading and no caption under the video either — the recording is the explanation, and writing it out again beside it was saying the same thing three times.

**Memphis accents** come from the hero's own vocabulary — the orange arch with its pink dot, the yellow sunburst, the purple zigzag, the dashed turquoise donut — so the section reads as the same hand. They hang off a `w-fit` wrapper around the heading rather than the full-width `h2`, or they drift out to the container edge instead of sitting against the words. The pair flanking the step rail is `xl`-only: the recording runs nearly the full container width, so anything beside *it* would overlap or be clipped, and the gutter is only wide enough past `xl`.

**The recording sits below the steps, unframed** — the steps say where you are before the video says what happens there. A browser chrome was tried and removed: it was decoration that cost 40px of height the recording should have, on the one element the whole section exists to show.

The whole scene has to fit one viewport or `justify-center` clips it at both ends. Everything else is fixed height, so the video takes what is left: `max-w-[min(80rem,max(22rem,calc((100svh_-_16rem)*16/9)))]` — 1145×644 at a 1512×900 window, 932×524 at 1440×780, and container-capped at 1216 wide beyond that. Note the underscores — Tailwind arbitrary values cannot contain spaces, and `calc` requires them around `-`, so writing it without the escapes produces invalid CSS that is silently dropped.

The pin is **desktop-only and off under `prefers-reduced-motion`** — hijacking a phone's scroll to play a video traps someone who was trying to leave. Below `lg` the same markup becomes a tap-through stepper.

Recordings live at `videos/how-it-works/<step-id>.mp4` in the R2 bucket (`mise run media:sync`, source dir `~/Desktop/nego-lah-media/dist`), with an optional `<step-id>.jpg` poster alongside. Two levels of laziness: nothing is fetched until the section is within 200px of the viewport, and a step's `<source>` is only attached once that step has been reached. A step never gives its source back, so scrolling up does not re-fetch. The existing service-worker media bypass (SPEC-030) matches on extension, not filename, so these paths inherit it unchanged.

The placeholder is driven by **whether a step has decodable video**, not by an error: a `<source>` that 404s fires `error` on the `<source>` element rather than on `<video>`, so error-only detection left a black rectangle on screen.

**Housekeeping:** `id="how-it-works"` was duplicated (`ProductVideoShowcase.vue:180`, `NegotiationDemo.vue:153`). Both components are now deleted, so the id belongs to the walkthrough alone. `home/NegotiationDemo.vue` + `home/AgentAvatar.vue` are orphaned and their story is already told twice — delete them with their tests and `home.dialog.*` / `home.demo.steps.*`. Also drop the dead keys the coverage test cannot see (it matches only literal `$t('…')`): `heroGreeting`, `heroName`, `heroTagline`, `perk*`, `heroDealCelebration`, `featuredListings`, `inputPlaceholder`.

# Test-Driven Development (TDD) Scenarios

- [x] **Late anchor:** a step whose `[data-tour]` element mounts *after* the step activates resolves once `revision` is bumped. Fails pre-fix — `reference` caches `undefined` forever.
- [x] **Stable list:** `total` never changes mid-tour, and `index` is not clamped when a step is skipped.
- [x] **Route hop:** `next()` across a route boundary navigates first, then advances.
- [x] **Persistence:** finish and skip both write `nego-lah-tour-v1`; no auto-start when it is present.
- [x] **Renderer:** `AppTour` shows the current title/body and `n / total`; Back disabled on step 1; Next reads "Finish" on the last.
- [x] **Orders API:** a shipped order returns courier/tracking/url/shipped_at; unshipped returns nulls; a URL is derived when `tracking_url` is null but the courier is known; another user's id is still rejected.
- [x] **Orders UI:** the tracking cell renders an external link, em dash when unshipped.
- [x] **Landing:** `index.test.ts` assertions at `:19-21`, `:44-46`, `:49-52` fail by design and are rewritten; i18n parity across en/ms/zh stays green.
- [x] **Walkthrough:** an unreached step has no `<source>`; a visited one keeps it; a step with nothing decodable says "Recording coming soon" and drops it on `loadeddata`; selecting a step in the stepper moves the video; the recording renders before the steps; no caption or subtitle repeats the video. `getBoundingClientRect` returns zeroes under happy-dom, so the scroll path is not covered — stepper selection is, and it is the only path a phone or reduced-motion visitor takes anyway.

# Implementation Files

- `frontend/app/pages/index.vue` - Reframed hero, CTA to login, section order
- `frontend/app/components/home/AgentPipeline.vue` - New: "How it works", pinned scroll + a video per step
- `frontend/app/composables/useOnboardingTour.ts` - New: step registry, route driving, anchor revision, persistence
- `frontend/app/components/tour/AppTour.vue` - New: popover renderer
- `frontend/app/app.vue` - Mount `AppTour` inside `UApp`
- `frontend/app/components/AppHeader.vue` - "How it works" replay item; `data-tour` on the avatar chip
- `frontend/app/pages/{items/index,items/[id],chat,orders}.vue`, `components/{ItemGrid,ItemCard}.vue` - `data-tour` anchors
- `frontend/app/locales/{en,ms,zh}.json` - New `tour.*`, rewritten `home.*`, dead keys removed
- `frontend/app/pages/orders.vue` - Tracking column
- `backend/routes/payment.py` - Project shipment fields in `get_user_orders`
- `frontend/app/types/database.types.ts` - Add the four `orders` shipment columns
- `frontend/app/components/home/{NegotiationDemo,AgentAvatar,ProductVideoShowcase,HouseRules}.vue` - Deleted
- `docs/adr/0023-the-design-system-already-had-a-tour.md` - New ADR
