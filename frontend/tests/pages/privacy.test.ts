import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import PrivacyPage from '~/pages/privacy.vue'

describe('pages/privacy.vue', () => {
  it('renders the privacy policy heading and last-updated date', async () => {
    const wrapper = await mountSuspended(PrivacyPage)
    expect(wrapper.find('h1').text()).toBe('Privacy Policy')
    expect(wrapper.text()).toContain('Last updated: June 2026')
  })
})
