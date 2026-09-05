import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import NegotiationDemo from '~/components/home/NegotiationDemo.vue'

describe('components/home/NegotiationDemo.vue', () => {
  it('renders the #how-it-works section with heading and description', async () => {
    const wrapper = await mountSuspended(NegotiationDemo)

    const section = wrapper.find('#how-it-works')
    expect(section.exists()).toBe(true)

    // Heading h2 exists
    const h2 = wrapper.find('h2')
    expect(h2.exists()).toBe(true)

    // Memphis wave underline SVG inside heading
    const headingSvg = h2.find('svg')
    expect(headingSvg.exists()).toBe(true)
  })

  it('renders all 3 step buttons with numerals 01, 02, 03', async () => {
    const wrapper = await mountSuspended(NegotiationDemo)

    // Step buttons are rendered via motion.button -> <button>
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(3)

    const allText = wrapper.text()
    expect(allText).toContain('01')
    expect(allText).toContain('02')
    expect(allText).toContain('03')
  })

  it('renders all 5 dialogue beats with agent and buyer speakers', async () => {
    const wrapper = await mountSuspended(NegotiationDemo)
    const html = wrapper.html()

    // All dialogue lines should appear (rendered via i18n)
    // Prices RM320, RM240, RM280 appear in the English locale dialogue
    expect(html).toContain('RM320')
    expect(html).toContain('RM240')
    expect(html).toContain('RM280')

    // Agent avatar SVGs (HomeAgentAvatar renders an SVG with agentAvatarGrad)
    expect(html).toContain('agentAvatarGrad')

    // Buyer badge shows "You"
    expect(wrapper.text()).toContain('You')
  })

  it('renders the mobile step description panel', async () => {
    const wrapper = await mountSuspended(NegotiationDemo)

    // Mobile panel uses sm:hidden class
    const mobilePanel = wrapper.find('.sm\\:hidden')
    expect(mobilePanel.exists()).toBe(true)
  })

  it('renders Memphis decoration shapes', async () => {
    const wrapper = await mountSuspended(NegotiationDemo)

    // Memphis ambience container
    const memphisContainer = wrapper.find('[aria-hidden="true"]')
    expect(memphisContainer.exists()).toBe(true)

    // Should contain decorative SVGs (star + arch)
    const svgs = memphisContainer.findAll('svg')
    expect(svgs.length).toBeGreaterThanOrEqual(2)
  })

  it('applies h-[300vh] scroll track when motion is not reduced', async () => {
    const wrapper = await mountSuspended(NegotiationDemo)

    // The track div uses the class conditionally via :class binding
    // Since useReducedMotion returns ref(false), it should apply the tall class
    const trackDiv = wrapper.find('.h-\\[300vh\\]')
    expect(trackDiv.exists()).toBe(true)
  })
})
