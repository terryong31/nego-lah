import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { TOUR_STEPS, TOUR_STORAGE_KEY, useOnboardingTour } from '../../app/composables/useOnboardingTour'

/**
 * SPEC-069 / ADR 0023.
 *
 * The tour is Nuxt UI's headless `useTour` plus the three things it does not
 * do: persistence, route awareness, and re-resolving an anchor that was not in
 * the DOM when its step activated.
 *
 * That last one is the reason most of this file exists. `useTour`'s
 * `reference` is a plain computed over `document.querySelector`, and the DOM
 * is not one of its reactive dependencies — so a target that mounts a tick
 * late resolves `undefined` and never recovers. Across four routes, a
 * `<ClientOnly>` header and a `v-if`'d chat header, that is the normal case.
 *
 * Run in an effect scope rather than a mounted component: the composable is a
 * module-level singleton and a component instance would unwrap the refs under
 * assertion.
 */

const navigateToMock = vi.hoisted(() => vi.fn(async (to: string) => {
  window.history.replaceState({}, '', to)
}))

mockNuxtImport('navigateTo', () => navigateToMock)

let scope: ReturnType<typeof effectScope>

function mountTour() {
  return scope.run(() => useOnboardingTour())!
}

/** Put a tour anchor in the document, the way a page component would. */
function plantAnchor(name: string, extra: Record<string, string> = {}) {
  const el = document.createElement('div')
  el.setAttribute('data-tour', name)
  for (const [k, v] of Object.entries(extra)) el.setAttribute(k, v)
  document.body.appendChild(el)
  return el
}

beforeEach(() => {
  vi.useFakeTimers()
  scope = effectScope()
  document.body.innerHTML = ''
  localStorage.clear()
  navigateToMock.mockClear()
  window.history.replaceState({}, '', '/items')
})

afterEach(() => {
  const tour = scope.run(() => useOnboardingTour())
  tour?.reset()
  scope.stop()
  vi.useRealTimers()
})

describe('the step list is stable', () => {
  it('never changes length once the tour is running', async () => {
    // useTour clamps `index` to `total` and force-closes at zero steps, so a
    // per-route filtered list would collapse the tour on every navigation.
    const tour = mountTour()
    const before = tour.total.value

    tour.start()
    await vi.advanceTimersByTimeAsync(1000)
    await tour.next()
    await vi.advanceTimersByTimeAsync(1000)

    expect(tour.total.value).toBe(before)
    expect(tour.total.value).toBe(TOUR_STEPS.length)
  })

  it('opens on the first step', () => {
    const tour = mountTour()
    tour.start()

    expect(tour.open.value).toBe(true)
    expect(tour.index.value).toBe(0)
    expect(tour.current.value?.id).toBe(TOUR_STEPS[0]!.id)
  })
})

describe('anchor resolution', () => {
  it('resolves a step whose anchor is already mounted', async () => {
    plantAnchor('items-search')
    const tour = mountTour()

    tour.goTo(TOUR_STEPS.findIndex(s => s.anchor === 'items-search'))
    await vi.advanceTimersByTimeAsync(500)

    expect(tour.reference.value).toBeInstanceOf(HTMLElement)
    expect((tour.reference.value as HTMLElement).getAttribute('data-tour')).toBe('items-search')
  })

  it('resolves an anchor that only mounts AFTER its step activated', async () => {
    // The regression this whole design exists for. Pre-fix, `reference` reads
    // the DOM once at activation and no later mutation can dislodge the
    // result, so the popover stays stuck wherever it first landed.
    const tour = mountTour()

    tour.goTo(TOUR_STEPS.findIndex(s => s.anchor === 'items-search'))
    await vi.advanceTimersByTimeAsync(0)
    // Nothing to point at yet: centred, and still looking.
    expect(tour.reference.value).not.toBeInstanceOf(HTMLElement)
    expect(tour.isSettling.value).toBe(true)

    plantAnchor('items-search')
    await vi.advanceTimersByTimeAsync(500)

    expect(tour.reference.value).toBeInstanceOf(HTMLElement)
    expect((tour.reference.value as HTMLElement).getAttribute('data-tour')).toBe('items-search')
    expect(tour.isSettling.value).toBe(false)
  })

  it('anchors a step with no target to the viewport centre rather than nothing', async () => {
    const tour = mountTour()

    tour.start()
    await vi.advanceTimersByTimeAsync(0)

    // Step 1 is a centred welcome: it must still produce a usable anchor.
    expect(TOUR_STEPS[0]!.anchor).toBeNull()
    expect(tour.reference.value).toBeDefined()
    expect(typeof tour.reference.value!.getBoundingClientRect).toBe('function')
  })

  it('gives up on a missing anchor instead of hanging, and centres the step', async () => {
    const tour = mountTour()

    tour.goTo(TOUR_STEPS.findIndex(s => s.anchor === 'items-search'))
    await vi.advanceTimersByTimeAsync(5000)

    expect(tour.open.value).toBe(true)
    expect(tour.isSettling.value).toBe(false)
  })
})

describe('crossing routes', () => {
  it('navigates before advancing, so the popover never activates on a dead anchor', async () => {
    const tour = mountTour()
    const from = TOUR_STEPS.findIndex(s => s.anchor === 'item-card-price')
    const to = from + 1

    expect(TOUR_STEPS[to]!.route).not.toBe(TOUR_STEPS[from]!.route)

    plantAnchor('item-card', { 'data-tour-item': 'item-42' })
    tour.goTo(from)
    await vi.advanceTimersByTimeAsync(500)

    await tour.next()

    expect(navigateToMock).toHaveBeenCalled()
    const target = navigateToMock.mock.calls.at(-1)![0]
    expect(target).toContain('item-42')
  })

  it('does not navigate between two steps on the same route', async () => {
    const tour = mountTour()
    const i = TOUR_STEPS.findIndex(s => s.anchor === 'items-search')
    expect(TOUR_STEPS[i]!.route).toBe(TOUR_STEPS[i + 1]!.route)

    plantAnchor('items-search')
    plantAnchor('items-filters')
    tour.goTo(i)
    await vi.advanceTimersByTimeAsync(500)
    navigateToMock.mockClear()

    await tour.next()
    await vi.advanceTimersByTimeAsync(500)

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(tour.index.value).toBe(i + 1)
  })

  it('skips the item and chat steps when the storefront has nothing to sell', async () => {
    // Every card sold means no [data-tour="item-card"] in the grid, so there
    // is no listing to open and no negotiation to point at.
    const tour = mountTour()
    const last = TOUR_STEPS.findIndex(s => s.anchor === 'item-card-price')

    tour.goTo(last)
    await vi.advanceTimersByTimeAsync(500)
    await tour.next()

    expect(tour.current.value?.route).toBe('/orders')
    expect(navigateToMock).toHaveBeenCalledWith('/orders')
  })
})

describe('persistence', () => {
  it('records completion when the tour finishes', async () => {
    const tour = mountTour()
    tour.start()
    tour.finish()

    expect(JSON.parse(localStorage.getItem(TOUR_STORAGE_KEY)!).done).toBe(true)
    expect(tour.open.value).toBe(false)
  })

  it('records completion when the tour is skipped', async () => {
    const tour = mountTour()
    tour.start()
    tour.skip()

    expect(JSON.parse(localStorage.getItem(TOUR_STORAGE_KEY)!).done).toBe(true)
    expect(tour.open.value).toBe(false)
  })

  it('remembers the step it was on, so a reload resumes rather than restarts', async () => {
    const tour = mountTour()
    tour.goTo(2)
    await vi.advanceTimersByTimeAsync(500)

    expect(JSON.parse(localStorage.getItem(TOUR_STORAGE_KEY)!).step).toBe(2)
  })

  it('auto-starts once for a signed-in buyer who has not seen it', async () => {
    const tour = mountTour()

    expect(tour.maybeAutoStart()).toBe(true)
    expect(tour.open.value).toBe(true)
  })

  it('resumes a saved step only when it belongs to the page we are on', async () => {
    const tour = mountTour()
    const chatStep = TOUR_STEPS.findIndex(s => s.anchor === 'chat-composer')
    localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify({ step: chatStep }))

    // We are on /items; the saved step lives on /chat, so it is stale.
    expect(tour.maybeAutoStart()).toBe(true)
    expect(tour.index.value).toBe(0)
    expect(navigateToMock).not.toHaveBeenCalled()
  })

  it('resumes mid-tour after a reload on the same page', async () => {
    const tour = mountTour()
    const searchStep = TOUR_STEPS.findIndex(s => s.anchor === 'items-search')
    localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify({ step: searchStep }))

    expect(tour.maybeAutoStart()).toBe(true)
    expect(tour.index.value).toBe(searchStep)
  })

  it('does not auto-start again once completed', async () => {
    const tour = mountTour()
    tour.start()
    tour.finish()

    expect(tour.maybeAutoStart()).toBe(false)
    expect(tour.open.value).toBe(false)
  })

  it('replays on an explicit start even after completion', async () => {
    const tour = mountTour()
    tour.start()
    tour.finish()

    tour.start()

    expect(tour.open.value).toBe(true)
    expect(tour.index.value).toBe(0)
  })

  it('survives storage being unavailable', async () => {
    // Private windows and blocked site data make the accessor itself throw.
    // Stub the global rather than Storage.prototype: happy-dom's localStorage
    // does not route through the prototype a spy would patch.
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      },
      removeItem: () => {
        throw new Error('denied')
      }
    })

    const tour = mountTour()
    expect(() => tour.start()).not.toThrow()
    expect(() => tour.finish()).not.toThrow()
    // A tour that cannot remember it ran offers itself again -- annoying at
    // worst, where swallowing the error the other way would hide it forever.
    expect(tour.maybeAutoStart()).toBe(true)

    vi.unstubAllGlobals()
  })
})
