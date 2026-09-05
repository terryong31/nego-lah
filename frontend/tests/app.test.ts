import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockComponent, mountSuspended } from '@nuxt/test-utils/runtime'
import App from '~/app.vue'

// app.vue's own responsibility is just SEO meta + wiring UApp > NuxtLayout >
// NuxtPage together. The actual layout/page content is covered by
// tests/layouts/default.test.ts and the individual tests/pages/*.test.ts
// files. Mounting the *real* NuxtLayout + NuxtPage here would render the
// real default layout wrapping whatever page the router's initial location
// resolves to (index.vue), which fetches '/items/featured' via the real
// unmocked $fetch/useApi and would fire an actual (doomed) network request
// under test. Stub both so this file stays scoped to app.vue's own template
// and never touches the network.
mockComponent('NuxtLayout', {
  template: '<div class="layout-stub"><slot /></div>'
})
mockComponent('NuxtPage', {
  template: '<div class="page-stub">page content</div>'
})

let activeWrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

afterEach(() => {
  activeWrapper?.unmount()
  activeWrapper = undefined
})

describe('app.vue', () => {
  it('renders NuxtPage nested inside NuxtLayout (wrapped by UApp)', async () => {
    activeWrapper = await mountSuspended(App)

    const layout = activeWrapper.find('.layout-stub')
    expect(layout.exists()).toBe(true)

    // NuxtPage must render *inside* NuxtLayout's default slot, not beside it.
    const page = layout.find('.page-stub')
    expect(page.exists()).toBe(true)
    expect(page.text()).toBe('page content')
  })

  it('sets the page title and meta description via useSeoMeta', async () => {
    activeWrapper = await mountSuspended(App)

    // useSeoMeta's DOM side effects are applied asynchronously (a plain
    // nextTick()/flushPromises() is not enough to observe them here), so
    // poll for the expected <title> instead of asserting immediately.
    await vi.waitFor(() => {
      expect(document.title).toBe('Nego-Lah')
    })

    const description = document.head.querySelector('meta[name="description"]')
    expect(description?.getAttribute('content')).toBe('AI powered e-commerce site. From image to sales.')

    const ogTitle = document.head.querySelector('meta[property="og:title"]')
    expect(ogTitle?.getAttribute('content')).toBe('Nego-Lah · Autonomous AI Price Negotiation Marketplace')

    const ogDescription = document.head.querySelector('meta[property="og:description"]')
    expect(ogDescription?.getAttribute('content')).toBe('AI powered e-commerce site. From image to sales.')

    const ogSiteName = document.head.querySelector('meta[property="og:site_name"]')
    expect(ogSiteName?.getAttribute('content')).toBe('Nego-Lah')

    const twitterTitle = document.head.querySelector('meta[name="twitter:title"]')
    expect(twitterTitle?.getAttribute('content')).toBe('Nego-Lah · Autonomous AI Price Negotiation Marketplace')

    const twitterDescription = document.head.querySelector('meta[name="twitter:description"]')
    expect(twitterDescription?.getAttribute('content')).toBe('AI powered e-commerce site. From image to sales.')

    const ogImage = document.head.querySelector('meta[property="og:image"]')
    expect(ogImage?.getAttribute('content')).toBe('https://negolah.my/og-image.png')

    const twitterCard = document.head.querySelector('meta[name="twitter:card"]')
    expect(twitterCard?.getAttribute('content')).toBe('summary_large_image')

    const twitterImage = document.head.querySelector('meta[name="twitter:image"]')
    expect(twitterImage?.getAttribute('content')).toBe('https://negolah.my/og-image.png')

    expect(document.documentElement.getAttribute('lang')).toBe('en')
  })

  it('mounts without throwing and produces a non-empty root element', async () => {
    activeWrapper = await mountSuspended(App)

    expect(activeWrapper.exists()).toBe(true)
    expect(activeWrapper.html().length).toBeGreaterThan(0)
  })
})
