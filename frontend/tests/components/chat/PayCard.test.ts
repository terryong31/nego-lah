import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import PayCard from '~/components/chat/PayCard.vue'

const URL = 'https://buy.stripe.com/session-abc'

describe('components/chat/PayCard.vue', () => {
  it('makes the agreed amount the hero, parsed out of the agent-authored label', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Pay RM1000 Now' }
    })

    expect(wrapper.text()).toContain('RM 1000.00')
    expect(wrapper.text()).toContain('Deal agreed')
    // The raw agent phrasing is replaced by the localised CTA.
    expect(wrapper.text()).not.toContain('Pay RM1000 Now')
    expect(wrapper.text()).toContain('Pay Now')
  })

  it('normalises a thousands-separated, already-decimal amount', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Pay RM1,199.50 Now' }
    })

    expect(wrapper.text()).toContain('RM 1199.50')
  })

  it('links out to the checkout url in a new tab, safely', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Pay RM50 Now' }
    })

    const link = wrapper.find('a')
    expect(link.attributes('href')).toBe(URL)
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('falls back to the raw label and the Stripe line when no amount can be parsed', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Complete checkout' }
    })

    expect(wrapper.text()).toContain('Complete checkout')
    expect(wrapper.text()).toContain('Complete your purchase securely via Stripe')
    expect(wrapper.text()).not.toContain('RM')
  })

  it('still renders a usable CTA when the agent sends no label at all', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL }
    })

    expect(wrapper.text()).toContain('Pay Now')
    expect(wrapper.find('a').attributes('href')).toBe(URL)
  })

  it('carries the Stripe trust footnote and keeps the decoration out of the a11y tree', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Pay RM50 Now' }
    })

    expect(wrapper.text()).toContain('Secured by')
    // The Stripe wordmark carries the brand name for screen readers, since the
    // visible copy stops at "Secured by".
    expect(wrapper.find('[aria-label="Stripe"]').exists()).toBe(true)
    expect(wrapper.find('svg[aria-hidden="true"]').exists()).toBe(true)
  })

  it('renders disabled state when paid is true', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Pay RM1000 Now', paid: true }
    })

    expect(wrapper.text()).toContain('Payment Completed')
    expect(wrapper.find('a').exists()).toBe(false)
    const btn = wrapper.find('button')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('renders disabled state when disabled prop is true', async () => {
    const wrapper = await mountSuspended(PayCard, {
      props: { url: URL, label: 'Pay RM500 Now', disabled: true }
    })

    expect(wrapper.text()).toContain('Payment Completed')
    expect(wrapper.find('a').exists()).toBe(false)
    const btn = wrapper.find('button')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeDefined()
  })
})
