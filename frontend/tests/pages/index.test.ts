import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import IndexPage from '~/pages/index.vue'

describe('pages/index.vue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('corporate memphis hero section', () => {
    it('renders the Corporate Memphis headline, CTAs and hero illustration', async () => {
      const wrapper = await mountSuspended(IndexPage)

      // Headline and brand name
      expect(wrapper.text()).toContain('Find something you like?')
      expect(wrapper.text()).toContain('Come')
      expect(wrapper.text()).toContain('Nego-lah')
      expect(wrapper.text()).toContain('Browse my stuff')

      // Renders the hero illustration
      expect(wrapper.find('img[src*="hero-illustration"]').exists()).toBe(true)
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
    it('renders the negotiation demo, house rules, and deployment pitch', async () => {
      const wrapper = await mountSuspended(IndexPage)

      // Negotiation demo section
      expect(wrapper.text()).toContain('It opens at RM320.')
      expect(wrapper.text()).toContain('won\'t pay that.')
      expect(wrapper.text()).not.toContain('Name your price')

      // House rules section
      expect(wrapper.text()).toContain('Three things I won\'t budge on')
      expect(wrapper.text()).toContain('I photograph the scratches')
      expect(wrapper.text()).toContain('Your money waits in Stripe')
      expect(wrapper.text()).toContain('Priced and shipped in Malaysia')

      // B2B deploy pitch section
      expect(wrapper.text()).toContain('Want this running inside your company?')
      expect(wrapper.text()).toContain('Frequently Asked Questions')
      expect(wrapper.text()).toContain('Nego-lah bukan pet project or mockup')
      expect(wrapper.findComponent({ name: 'UAccordion' }).exists()).toBe(true)
    })

    it('drops the bottom CTA banner but keeps a route into the catalogue', async () => {
      const wrapper = await mountSuspended(IndexPage)

      expect(wrapper.text()).not.toContain('Come, try to break my AI')

      const exploreBtn = wrapper
        .findAllComponents({ name: 'UButton' })
        .find(b => b.props('to') === '/items')
      expect(exploreBtn).toBeDefined()
    })

    it('renders the product walkthrough video showcase with Memphis styling', async () => {
      const wrapper = await mountSuspended(IndexPage)

      // Video showcase frame and video element
      expect(wrapper.find('[data-testid="video-showcase-frame"]').exists()).toBe(true)
      expect(wrapper.find('video').exists()).toBe(true)
      expect(wrapper.find('.animate-memphis-float').exists()).toBe(true)
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
