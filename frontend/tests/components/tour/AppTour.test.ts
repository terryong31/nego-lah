import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import AppTour from '~/components/tour/AppTour.vue'
import { TOUR_STEPS, useOnboardingTour } from '~/composables/useOnboardingTour'

/**
 * SPEC-069. The renderer over `useOnboardingTour`.
 *
 * `UPopover` portals its content to `document.body`, so the assertions read
 * from there rather than from the wrapper — the same pattern as
 * tests/components/admin/AdminChatsRowActions.test.ts.
 */

const navigateToMock = vi.hoisted(() => vi.fn(async (to: string) => {
  window.history.replaceState({}, '', to)
}))

mockNuxtImport('navigateTo', () => navigateToMock)

function tour() {
  return useOnboardingTour()
}

/** Anchors planted for a single test, removed individually afterwards. */
const planted: Element[] = []

function plantAnchor(name: string) {
  const el = document.createElement('div')
  el.setAttribute('data-tour', name)
  document.body.appendChild(el)
  planted.push(el)
  return el
}

// Unmount between tests rather than clearing document.body: the mount
// container belongs to the shared Nuxt test app, and wiping it leaves every
// later mount detached, where a portalled popover renders nothing at all.
enableAutoUnmount(afterEach)

beforeEach(() => {
  localStorage.clear()
  navigateToMock.mockClear()
  window.history.replaceState({}, '', '/items')
  tour().reset()
})

afterEach(() => {
  tour().reset()
  planted.splice(0).forEach(el => el.remove())
})

describe('components/tour/AppTour.vue', () => {
  it('renders nothing until the tour is started', async () => {
    await mountSuspended(AppTour)

    expect(document.body.textContent).not.toContain('The seller here is an AI')
  })

  it('renders the current step title and body', async () => {
    await mountSuspended(AppTour)

    await tour().start()
    await flushPromises()

    expect(document.body.textContent).toContain('The seller here is an AI')
    expect(document.body.textContent).toContain('haggles in ringgit')
  })

  it('shows how far through the tour the reader is', async () => {
    await mountSuspended(AppTour)

    await tour().start()
    await flushPromises()

    expect(document.body.textContent).toContain(`1 of ${TOUR_STEPS.length}`)
  })

  it('offers no way back from the first step', async () => {
    const wrapper = await mountSuspended(AppTour)

    await tour().start()
    await flushPromises()

    const back = wrapper.find('[data-testid="tour-back"]')
    expect(back.exists() ? back.attributes('disabled') !== undefined : true).toBe(true)
  })

  it('labels the last step Done rather than Next', async () => {
    await mountSuspended(AppTour)

    await tour().goTo(TOUR_STEPS.length - 1)
    await flushPromises()

    expect(document.body.textContent).toContain('Done')
    expect(document.body.textContent).toContain('That is the tour')
  })

  it('closes and records completion when skipped', async () => {
    await mountSuspended(AppTour)

    await tour().start()
    await flushPromises()

    tour().skip()
    await flushPromises()

    expect(tour().open.value).toBe(false)
    expect(tour().isCompleted()).toBe(true)
  })

  it('illustrates the checkout card on the step that has none to point at', async () => {
    await mountSuspended(AppTour)

    await tour().goTo(TOUR_STEPS.findIndex(s => s.id === 'payCard'))
    await flushPromises()

    // A brand-new buyer has never seen a PayCard, so the step draws one.
    expect(document.body.textContent).toContain('Pay RM280')
    expect(document.body.textContent).toContain('Secured by Stripe')
  })

  it('marks the live anchor so the reader can see what is being pointed at', async () => {
    const anchor = plantAnchor('items-search')

    await mountSuspended(AppTour)
    await tour().goTo(TOUR_STEPS.findIndex(s => s.anchor === 'items-search'))
    await flushPromises()

    expect(anchor.hasAttribute('data-tour-active')).toBe(true)

    tour().skip()
    await flushPromises()

    // And unmarks it, so nothing is left highlighted after the tour ends.
    expect(anchor.hasAttribute('data-tour-active')).toBe(false)
  })
})
