import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import AppLogo from '~/components/AppLogo.vue'

describe('AppLogo.vue', () => {
  it('renders the SVG brand mark and Nego-Lah brand text by default', async () => {
    const wrapper = await mountSuspended(AppLogo)

    // Must render the SVG icon
    const svg = wrapper.find('svg')
    expect(svg.exists()).toBe(true)

    // Must render the text parts
    expect(wrapper.text()).toContain('Nego')
    expect(wrapper.text()).toMatch(/lah/i)
  })

  it('hides the brand text when hideText prop is true', async () => {
    const wrapper = await mountSuspended(AppLogo, {
      props: { hideText: true }
    })

    const svg = wrapper.find('svg')
    expect(svg.exists()).toBe(true)
    expect(wrapper.text()).toBe('')
  })

  it('applies the appropriate size classes for sm, md, and lg', async () => {
    const wrapperSm = await mountSuspended(AppLogo, { props: { size: 'sm' } })
    expect(wrapperSm.find('svg').classes()).toContain('size-6')

    const wrapperMd = await mountSuspended(AppLogo, { props: { size: 'md' } })
    expect(wrapperMd.find('svg').classes()).toContain('size-8')

    const wrapperLg = await mountSuspended(AppLogo, { props: { size: 'lg' } })
    expect(wrapperLg.find('svg').classes()).toContain('size-10')
  })
})
