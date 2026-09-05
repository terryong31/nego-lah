import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import StatusScene from '~/components/checkout/StatusScene.vue'

describe('components/checkout/StatusScene.vue', () => {
  it('tints the mark with the semantic colour of each outcome', async () => {
    const cases = [
      ['success', 'text-primary'],
      ['refunded', 'text-warning'],
      ['error', 'text-error'],
      ['pending', 'text-primary']
    ] as const

    for (const [variant, expected] of cases) {
      const wrapper = await mountSuspended(StatusScene, { props: { variant } })
      expect(wrapper.find('svg').classes()).toContain(expected)
    }
  })

  it('thins the confetti out as the news gets worse', async () => {
    const count = async (variant: 'success' | 'refunded' | 'error') => {
      const wrapper = await mountSuspended(StatusScene, { props: { variant } })
      // One svg for the mark plus one per accent shape.
      return wrapper.findAll('svg').length
    }

    expect(await count('success')).toBe(5)
    expect(await count('refunded')).toBe(3)
    expect(await count('error')).toBe(2)
  })

  it('spins a dashed ring while pending instead of drawing a static mark', async () => {
    const wrapper = await mountSuspended(StatusScene, { props: { variant: 'pending' } })

    expect(wrapper.find('.animate-memphis-spin-slow').exists()).toBe(true)
    expect(wrapper.find('[stroke-dasharray]').exists()).toBe(true)
  })

  it('keeps the whole illustration out of the accessibility tree', async () => {
    const wrapper = await mountSuspended(StatusScene, { props: { variant: 'success' } })

    expect(wrapper.attributes('aria-hidden')).toBe('true')
  })
})
