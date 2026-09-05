import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import MemphisCharacters from '~/components/hero/MemphisCharacters.vue'

describe('components/hero/MemphisCharacters.vue', () => {
  it('renders the transparent character illustration and all 5 geometric accents', async () => {
    const wrapper = await mountSuspended(MemphisCharacters)

    // Illustration
    const img = wrapper.find('img[src*="hero-illustration.png"]')
    expect(img.exists()).toBe(true)

    // Musical notes near guitar headstock
    expect(wrapper.text()).toContain('♪')
    expect(wrapper.text()).toContain('♫')

    // SVG elements (Orange Arch, Yellow Star, Purple Zigzag, Turquoise Donut)
    const svgs = wrapper.findAll('svg')
    expect(svgs.length).toBeGreaterThanOrEqual(4)

    // Dotted Matrix element
    expect(wrapper.find('.grid-cols-4').exists()).toBe(true)
  })
})
