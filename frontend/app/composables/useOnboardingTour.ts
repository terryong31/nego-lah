/**
 * The buyer onboarding tour (SPEC-069 / ADR 0023).
 *
 * Nuxt UI ships `useTour`, which owns the step index and resolves the anchor
 * for a single `UPopover` that re-points between steps. It deliberately owns
 * nothing else, so this composable supplies the three things a tour spanning
 * `/items` -> `/items/[id]` -> `/chat` -> `/orders` actually needs:
 *
 *   1. Anchor re-resolution. `useTour`'s `reference` is a plain computed over
 *      `document.querySelector`, and the DOM is NOT one of its reactive
 *      dependencies. A target that is not mounted the instant its step
 *      activates resolves `undefined` and never recovers — no error, no retry,
 *      just a popover floating in the corner. Reading `revision` inside each
 *      step's target getter is what enrols the DOM in that computed's
 *      dependency graph; `settleAnchor` then bumps it until the element turns
 *      up or the budget runs out.
 *   2. Route awareness. Navigation happens BEFORE the index advances, so a
 *      step never activates against a page that has already unmounted.
 *   3. Persistence, so it runs once and can be replayed on demand.
 *
 * Two constraints out of `useTour`'s implementation shape everything here:
 * `index` is clamped to `total` and the tour force-closes at zero steps. So
 * the step list is built once and never filtered — a step that does not apply
 * is skipped by advancing past it.
 */
import { effectScope } from 'vue'

export const TOUR_STORAGE_KEY = 'nego-lah-tour-v1'

/** How long to keep looking for an anchor before centring the step instead. */
const SETTLE_INTERVAL_MS = 50
const SETTLE_ATTEMPTS = 20

export interface OnboardingStep {
  /** Stable id, and the i18n key under `tour.steps`. */
  id: string
  /**
   * The `data-tour` attribute this step points at, or `null` for a step that
   * is centred in the viewport on purpose — a welcome, a sign-off, or an
   * explanation of something a brand-new buyer has no instance of yet.
   */
  anchor: string | null
  /**
   * Route pattern the step lives on. `[id]` is substituted with the listing
   * the tour picked up off the storefront. `null` means "wherever we are" —
   * used for anchors that live in the persistent header.
   */
  route: string | null
  /** Steps that make no sense when the storefront has nothing available. */
  requiresItem?: boolean
  /** Popover placement hint, passed through to `UPopover`. */
  side?: 'top' | 'bottom' | 'left' | 'right'
}

/**
 * Listing -> negotiate -> pay -> track, in the order a buyer meets them.
 *
 * Buy Now is described but never clicked: its handler assigns
 * `window.location.href` to the Stripe URL, which tears the SPA down and takes
 * the tour with it.
 */
export const TOUR_STEPS: readonly OnboardingStep[] = [
  { id: 'welcome', anchor: null, route: '/items' },
  { id: 'search', anchor: 'items-search', route: '/items', side: 'bottom' },
  { id: 'filters', anchor: 'items-filters', route: '/items', side: 'bottom' },
  { id: 'price', anchor: 'item-card-price', route: '/items', side: 'top' },
  { id: 'listing', anchor: 'item-detail-price', route: '/items/[id]', requiresItem: true, side: 'bottom' },
  { id: 'buyNow', anchor: 'item-buy-now', route: '/items/[id]', requiresItem: true, side: 'top' },
  { id: 'negotiate', anchor: 'item-negotiate', route: '/items/[id]', requiresItem: true, side: 'top' },
  { id: 'chatPrice', anchor: 'chat-item-price', route: '/chat', requiresItem: true, side: 'bottom' },
  { id: 'composer', anchor: 'chat-composer', route: '/chat', requiresItem: true, side: 'top' },
  { id: 'payCard', anchor: null, route: '/chat', requiresItem: true },
  { id: 'notifications', anchor: 'header-user', route: null, requiresItem: true, side: 'bottom' },
  { id: 'orders', anchor: 'orders-table', route: '/orders', side: 'bottom' },
  { id: 'done', anchor: null, route: '/orders' }
]

interface StoredProgress {
  done?: boolean
  step?: number
}

/** localStorage is unavailable outright in some contexts, and throws in others. */
function readProgress(): StoredProgress {
  try {
    const raw = localStorage.getItem(TOUR_STORAGE_KEY)
    return raw ? JSON.parse(raw) as StoredProgress : {}
  } catch {
    return {}
  }
}

function writeProgress(progress: StoredProgress) {
  try {
    localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify(progress))
  } catch {
    // A tour that cannot remember it ran is still a working tour.
  }
}

function anchorEl(name: string): Element | undefined {
  if (typeof document === 'undefined') return undefined
  return document.querySelector(`[data-tour="${name}"]`) ?? undefined
}

function currentPath(): string {
  return typeof window === 'undefined' ? '' : window.location.pathname
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

interface TourSingleton {
  revision: Ref<number>
  isSettling: Ref<boolean>
  itemId: Ref<string | null>
  tour: ReturnType<typeof useTour>
  /** Shared so every caller of the composable drives the same search. */
  settle: { timer: ReturnType<typeof setTimeout> | null, observer: MutationObserver | null }
}

let singleton: TourSingleton | null = null

function getSingleton(): TourSingleton {
  if (singleton) return singleton

  const revision = ref(0)
  const isSettling = ref(false)
  const itemId = ref<string | null>(null)

  const steps = TOUR_STEPS.map(step => ({
    ...step,
    target: () => {
      // Reading `revision` is the whole trick — see the file header.
      void revision.value
      if (!step.anchor) return null
      // `useTour` compares `target == null`, so there is no third state to
      // return here: anything that is not an element centres the popover.
      // A step whose anchor has not mounted yet therefore shows centred and
      // re-points the moment `settleAnchor` finds it — `isSettling` is what
      // lets the renderer tell that apart from a deliberately centred step.
      return anchorEl(step.anchor) ?? null
    }
  }))

  // Detached so the composable's first caller — a component that later
  // unmounts, or a test's effect scope — cannot dispose state the rest of the
  // app still depends on.
  const scope = effectScope(true)
  const tour = scope.run(() => useTour(steps, {
    scrollIntoView: {
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'center'
    }
  }))!

  singleton = { revision, isSettling, itemId, tour, settle: { timer: null, observer: null } }
  return singleton
}

export function useOnboardingTour() {
  const { revision, isSettling, itemId, tour, settle } = getSingleton()

  function stopSettling() {
    if (settle.timer) {
      clearTimeout(settle.timer)
      settle.timer = null
    }
    settle.observer?.disconnect()
    settle.observer = null
    isSettling.value = false
    revision.value++
  }

  /**
   * Keep looking for the active step's anchor until it mounts, or until the
   * budget runs out and the step is centred instead. A route change, a
   * `<ClientOnly>` swap and a `v-if` all land after the step activates.
   */
  function settleAnchor() {
    if (settle.timer) clearTimeout(settle.timer)
    settle.observer?.disconnect()
    settle.observer = null
    settle.timer = null

    const step = TOUR_STEPS[tour.index.value]
    if (!step?.anchor) {
      isSettling.value = false
      revision.value++
      return
    }
    if (anchorEl(step.anchor)) {
      isSettling.value = false
      revision.value++
      return
    }

    isSettling.value = true
    revision.value++

    let attempts = 0
    const tick = () => {
      revision.value++
      if (anchorEl(step.anchor!) || ++attempts >= SETTLE_ATTEMPTS) {
        stopSettling()
        return
      }
      settle.timer = setTimeout(tick, SETTLE_INTERVAL_MS)
    }
    settle.timer = setTimeout(tick, SETTLE_INTERVAL_MS)

    if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
      settle.observer = new MutationObserver(() => {
        revision.value++
        if (anchorEl(step.anchor!)) stopSettling()
      })
      settle.observer.observe(document.body, { childList: true, subtree: true })
    }
  }

  /**
   * The listing the tour walks through, taken off the storefront: the first
   * card that is actually for sale marks itself, so a grid of sold-out items
   * yields nothing and the item-dependent steps are skipped.
   */
  function resolveItemId(): string | null {
    if (itemId.value) return itemId.value
    const card = anchorEl('item-card')
    const id = card?.getAttribute('data-tour-item') ?? null
    if (id) itemId.value = id
    return id
  }

  function resolvePath(step: OnboardingStep): string | null {
    if (!step.route) return null
    const id = resolveItemId()
    if (step.route === '/items/[id]') return id ? `/items/${id}` : null
    if (step.route === '/chat') return id ? `/chat?item_id=${id}` : '/chat'
    return step.route
  }

  async function goTo(i: number) {
    const step = TOUR_STEPS[i]
    if (!step) return

    const path = resolvePath(step)
    if (path && path.split('?')[0] !== currentPath()) {
      await navigateTo(path)
    }

    tour.goTo(i)
    writeProgress({ step: i })
    settleAnchor()
  }

  /** The next step that applies, or null when the tour is done. */
  function nextIndex(): number | null {
    const hasItem = !!resolveItemId()
    for (let i = tour.index.value + 1; i < TOUR_STEPS.length; i++) {
      if (TOUR_STEPS[i]!.requiresItem && !hasItem) continue
      return i
    }
    return null
  }

  function prevIndex(): number | null {
    const hasItem = !!resolveItemId()
    for (let i = tour.index.value - 1; i >= 0; i--) {
      if (TOUR_STEPS[i]!.requiresItem && !hasItem) continue
      return i
    }
    return null
  }

  async function next() {
    const i = nextIndex()
    if (i === null) return finish()
    await goTo(i)
  }

  async function prev() {
    const i = prevIndex()
    if (i === null) return
    await goTo(i)
  }

  function start(at = 0) {
    itemId.value = null
    return goTo(at)
  }

  function close(done: boolean) {
    stopSettling()
    tour.finish()
    if (done) writeProgress({ done: true })
  }

  /** Reached the end. */
  function finish() {
    close(true)
  }

  /** Bailed out early — same outcome: don't show it again unprompted. */
  function skip() {
    close(true)
  }

  function isCompleted(): boolean {
    return readProgress().done === true
  }

  /**
   * Called from the storefront once a buyer is signed in.
   *
   * A saved step is only resumed when it belongs to the page we are already
   * on — that is a reload mid-tour. Someone who wandered off and came back to
   * the storefront a week later gets the tour from the top, not a sudden
   * redirect into a half-finished negotiation.
   */
  function maybeAutoStart(): boolean {
    if (isCompleted()) return false
    const { step } = readProgress()
    const saved = typeof step === 'number' && step > 0 && step < TOUR_STEPS.length
      ? TOUR_STEPS[step]!
      : null
    const resumable = saved && saved.route === currentPath()
    void start(resumable ? step as number : 0)
    return true
  }

  /** Drop every trace of the tour. Used by tests and by a deliberate replay. */
  function reset() {
    stopSettling()
    tour.finish()
    tour.goTo(0)
    tour.finish()
    itemId.value = null
    try {
      localStorage.removeItem(TOUR_STORAGE_KEY)
    } catch {
      // Nothing to clear if storage never worked in the first place.
    }
  }

  return {
    open: tour.open,
    index: tour.index,
    current: tour.current,
    reference: tour.reference,
    total: tour.total,
    hasNext: tour.hasNext,
    hasPrev: tour.hasPrev,
    isSettling,
    steps: TOUR_STEPS,
    start,
    next,
    prev,
    goTo,
    finish,
    skip,
    reset,
    isCompleted,
    maybeAutoStart
  }
}
