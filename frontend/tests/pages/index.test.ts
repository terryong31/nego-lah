import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import IndexPage from '~/pages/index.vue'

/**
 * SPEC-069 reframed this page: it used to sell one seller's stuff in the first
 * person, and now it has to read as an illustration of an agentic marketplace.
 * The assertions that changed here changed on purpose.
 */

const { userRef } = vi.hoisted(() => ({
  userRef: { __v_isRef: true, value: null as Record<string, unknown> | null }
}))

mockNuxtImport('useSupabaseUser', () => () => userRef)

describe('pages/index.vue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    userRef.value = null
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('corporate memphis hero section', () => {
    it('leads with the marketplace ghosting hook and AI seller value prop', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.text()).toContain('Hi, is this')
      expect(wrapper.text()).toContain('available?')
      expect(wrapper.text()).toContain('Facebook Marketplace')
      expect(wrapper.text()).toContain('negotiates and closes sales 24/7')

      // Renders the hero illustration
      expect(wrapper.find('img[src*="hero-illustration"]').exists()).toBe(true)
    })

    it('no longer speaks as one seller about his own stuff', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.text()).not.toContain('Browse my stuff')
      expect(wrapper.text()).not.toContain('Find something you like?')
      expect(wrapper.text()).not.toContain('I photograph the scratches')
    })

    it('centers content on mobile viewports via responsive utility classes', async () => {
      const wrapper = await mountSuspended(IndexPage)

      const heroTextCol = wrapper.find('.lg\\:col-span-6')
      expect(heroTextCol.classes()).toContain('items-center')
      expect(heroTextCol.classes()).toContain('text-center')
      expect(heroTextCol.classes()).toContain('lg:items-start')
      expect(heroTextCol.classes()).toContain('lg:text-left')
    })
  })

  describe('how it works and feature sections', () => {
    it('walks through how it works, upload to doorstep', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.text()).toContain('How it works')
      // Three steps, one word each; the recording explains them (SPEC-075).
      for (const step of ['Upload', 'Nego', 'Delivery']) {
        expect(wrapper.text()).toContain(step)
      }
      // The middle ceremony is gone from the story.
      expect(wrapper.text()).not.toContain('Memory')
      expect(wrapper.text()).not.toContain('Deal')
      expect(wrapper.text()).not.toContain('Paid')
      expect(wrapper.findComponent({ name: 'UStepper' }).exists()).toBe(true)
    })

    it('keeps exactly one #how-it-works anchor for deep links to land on', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.findAll('#how-it-works')).toHaveLength(1)
    })

    it('renders the deployment pitch', async () => {
      const wrapper = await mountSuspended(IndexPage)

      // B2B deploy pitch section
      expect(wrapper.text()).toContain('Want this running inside your company?')
      expect(wrapper.text()).toContain('Frequently Asked Questions')
      expect(wrapper.text()).toContain('Nego-lah bukan pet project or mockup')
      expect(wrapper.findComponent({ name: 'UAccordion' }).exists()).toBe(true)
    })

    it('sends a signed-out reader to log in, carrying the storefront as the return trip', async () => {
      const wrapper = await mountSuspended(IndexPage)

      // `loginRedirect` hands back a route object, not a string, so that the
      // return path survives encoding rather than being pasted into a URL.
      type LoginTarget = { path?: string, query?: { redirect?: string } }
      const ctas = wrapper
        .findAllComponents({ name: 'UButton' })
        .filter(b => (b.props('to') as LoginTarget | undefined)?.path === '/login')

      expect(ctas).toHaveLength(1)
      expect((ctas[0]!.props('to') as LoginTarget).query?.redirect).toBe('/items')
      expect(wrapper.text()).toContain('Try it')
    })

    it('sends a signed-in reader straight to the storefront instead', async () => {
      userRef.value = { id: 'u1' }
      const wrapper = await mountSuspended(IndexPage)

      const enter = wrapper
        .findAllComponents({ name: 'UButton' })
        .filter(b => b.props('to') === '/items')

      expect(enter).toHaveLength(1)
      expect(wrapper.text()).toContain('Enter the store')
      expect(wrapper.text()).not.toContain('Try it')
    })

    it('drops the standalone video showcase and the house rules', async () => {
      const wrapper = await mountSuspended(IndexPage)

      // Both sections were removed; the walkthrough carries the video now.
      expect(wrapper.text()).not.toContain('It opens at RM320.')
      expect(wrapper.text()).not.toContain('Three things')
      expect(wrapper.find('[data-testid="video-showcase-frame"]').exists()).toBe(false)
    })

    it('does not render the removed money track or status badge', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.text()).not.toContain('Where the money moved')
      expect(wrapper.text()).not.toContain('See it happen')
    })

    it('does not render old demo pills or unused stubs', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.find('.item-grid-stub').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('Featured Listings')
      expect(wrapper.text()).not.toContain('AI-Powered Secondhand Marketplace')
      expect(wrapper.text()).not.toContain('DEAL! 🤝')
    })
  })
})
