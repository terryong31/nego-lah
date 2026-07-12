import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import CancelPage from '~/pages/checkout/cancel.vue'

describe('pages/checkout/cancel.vue', () => {
  it('renders the payment cancelled heading', async () => {
    const wrapper = await mountSuspended(CancelPage)
    expect(wrapper.find('h2').text()).toBe('Payment Cancelled')
  })

  it('renders the cancellation message reassuring no charges were made', async () => {
    const wrapper = await mountSuspended(CancelPage)
    expect(wrapper.text()).toContain('Your Stripe transaction was cancelled. No charges were made to your account.')
  })

  it('renders a link back to the home page', async () => {
    const wrapper = await mountSuspended(CancelPage)
    const link = wrapper.find('a')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('/')
    expect(link.text()).toContain('View Items')
  })

  it('renders the warning alert icon', async () => {
    const wrapper = await mountSuspended(CancelPage)
    expect(wrapper.findComponent({ name: 'UIcon' }).exists()).toBe(true)
  })
})
