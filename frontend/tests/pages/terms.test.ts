import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import TermsPage from '~/pages/terms.vue'

describe('pages/terms.vue', () => {
  it('renders the terms of service heading and last-updated date', async () => {
    const wrapper = await mountSuspended(TermsPage)
    expect(wrapper.find('h1').text()).toBe('Terms of Service')
    expect(wrapper.text()).toContain('Last updated: June 2026')
  })

  it('renders all numbered section headings', async () => {
    const wrapper = await mountSuspended(TermsPage)
    const h2s = wrapper.findAll('h2').map(h => h.text())
    expect(h2s).toEqual([
      '1. Acceptance of Terms',
      '2. Your Account',
      '3. Negotiations and Pricing',
      '4. Orders and Payment',
      '5. Acceptable Use',
      '6. Disclaimer',
      '7. Limitation of Liability',
      '8. Changes to These Terms',
      '9. Contact'
    ])
  })

  it('renders the acceptable-use list items', async () => {
    const wrapper = await mountSuspended(TermsPage)
    const items = wrapper.findAll('li').map(li => li.text())
    expect(items).toHaveLength(3)
    expect(items[0]).toContain('unlawful or fraudulent purpose')
    expect(items[1]).toContain('reverse engineer')
    expect(items[2]).toContain('misrepresent items')
  })

  it('renders a mailto contact link', async () => {
    const wrapper = await mountSuspended(TermsPage)
    const link = wrapper.find('a[href="mailto:support@negolah.my"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toBe('support@negolah.my')
  })
})
