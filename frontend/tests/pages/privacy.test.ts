import { describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import PrivacyPage from '~/pages/privacy.vue'
import { PRIVACY_POLICY } from '~/utils/legal'

describe('pages/privacy.vue', () => {
  it('renders the privacy policy heading and last-updated date', async () => {
    const wrapper = await mountSuspended(PrivacyPage)
    expect(wrapper.find('h1').text()).toBe('Privacy Policy')
    expect(wrapper.text()).toContain(`Last updated: ${PRIVACY_POLICY.lastUpdated}`)
  })

  it('renders every numbered section', async () => {
    const wrapper = await mountSuspended(PrivacyPage)
    const headings = wrapper.findAll('h2').map(h => h.text())

    expect(headings).toEqual([
      '1. Introduction',
      '2. Information We Collect',
      '3. How We Use Your Information',
      '4. Google User Data',
      '5. AI Processing of Your Conversations',
      '6. How We Share Information',
      '7. Cookies and Local Storage',
      '8. International Transfers',
      '9. How Long We Keep Your Data',
      '10. Your Rights and Choices',
      '11. Security',
      '12. Children',
      '13. Changes and Contact'
    ])
  })

  // Google's OAuth verification checks the policy for these specific
  // disclosures. Losing one is what gets an app rejected, so they are asserted
  // rather than left to a reviewer to notice.
  describe('Google OAuth verification requirements', () => {
    it('names the Google data received and what each field is for', async () => {
      const text = (await mountSuspended(PrivacyPage)).text()

      expect(text).toContain('Sign in with Google')
      expect(text).toContain('your name, email address, profile picture and Google account identifier')
      expect(text).toContain('openid')
    })

    it('carries the Limited Use statement', async () => {
      const text = (await mountSuspended(PrivacyPage)).text().replace(/\s+/g, ' ')

      expect(text).toContain('Google API Services User Data Policy')
      expect(text).toContain('Limited Use')
      expect(text).toContain('We do not sell Google user data')
    })

    it('links to the Google policy and to the permissions revocation page', async () => {
      const wrapper = await mountSuspended(PrivacyPage)

      expect(wrapper.find('a[href="https://developers.google.com/terms/api-services-user-data-policy"]').exists()).toBe(true)
      expect(wrapper.find('a[href="https://myaccount.google.com/permissions"]').exists()).toBe(true)
    })

    it('states how data is shared, retained and deleted', async () => {
      const text = (await mountSuspended(PrivacyPage)).text().replace(/\s+/g, ' ')

      expect(text).toContain('We do not sell your personal data')
      expect(text).toContain('Delete your account')
      expect(text).toContain('deleted when you delete your account')
    })

    it('renders a mailto contact link', async () => {
      const link = (await mountSuspended(PrivacyPage)).find('a[href="mailto:support@negolah.my"]')
      expect(link.exists()).toBe(true)
    })
  })
})
