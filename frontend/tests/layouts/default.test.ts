import { describe, expect, it } from 'vitest'
import { mountSuspended, mockNuxtImport } from '@nuxt/test-utils/runtime'
import DefaultLayout from '~/layouts/default.vue'

const routeStub = { path: '/' }

mockNuxtImport('useRoute', () => () => routeStub)

describe('layouts/default.vue', () => {
  it('renders the AppHeader (brand link) and the slotted page content', async () => {
    routeStub.path = '/'
    const wrapper = await mountSuspended(DefaultLayout, {
      slots: { default: () => 'Page content goes here' }
    })

    // AppHeader renders a "Nego-lah" brand link to "/"
    expect(wrapper.text()).toContain('Nego-lah')
    const brandLink = wrapper.findAll('a').find(a => a.text() === 'Nego-lah')
    expect(brandLink).toBeTruthy()
    expect(brandLink!.attributes('href')).toBe('/')

    // default slot content is rendered inside the layout
    expect(wrapper.text()).toContain('Page content goes here')
  })

  it('renders the footer with privacy/terms/github links and current year copyright', async () => {
    routeStub.path = '/'
    const wrapper = await mountSuspended(DefaultLayout, {
      slots: { default: () => 'content' }
    })

    const text = wrapper.text()
    expect(text).toContain(`© Nego-lah ${new Date().getFullYear()}`)
    expect(text).toContain('Terry Ong')
    expect(text).toContain('Privacy')
    expect(text).toContain('Terms')

    const hrefs = wrapper.findAll('a').map(a => a.attributes('href'))
    expect(hrefs).toContain('/privacy')
    expect(hrefs).toContain('/terms')
  })

  it('does NOT apply the framed border classes to UMain when on the root path "/"', async () => {
    routeStub.path = '/'
    const wrapper = await mountSuspended(DefaultLayout, {
      slots: { default: () => 'root content' }
    })

    const main = wrapper.find('main')
    expect(main.exists()).toBe(true)
    expect(main.classes()).not.toContain('border-x')
    expect(main.classes()).not.toContain('border-default')
  })

  it('applies the framed border classes to UMain on any non-root path', async () => {
    routeStub.path = '/items/123'
    const wrapper = await mountSuspended(DefaultLayout, {
      slots: { default: () => 'item content' }
    })

    const main = wrapper.find('main')
    expect(main.exists()).toBe(true)
    expect(main.classes()).toContain('border-x')
    expect(main.classes()).toContain('border-default')
  })
})
