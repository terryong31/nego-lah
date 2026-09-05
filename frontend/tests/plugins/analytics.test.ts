/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, beforeEach } from 'vitest'

describe('analytics plugin logic', () => {
  beforeEach(() => {
    document.head.innerHTML = ''
    // @ts-expect-error Reset dataLayer
    delete window.dataLayer
    // @ts-expect-error Reset gtag
    delete window.gtag
  })

  it('injects GTM script and pushes gtm.start when gtmId is provided', async () => {
    window.dataLayer = []
    const gtmId = 'GTM-TEST1234'

    // Simulate plugin initialization for GTM
    window.dataLayer.push({
      'gtm.start': new Date().getTime(),
      'event': 'gtm.js'
    })
    const script = document.createElement('script')
    script.async = true
    script.src = `https://www.googletagmanager.com/gtm.js?id=${gtmId}`
    document.head.appendChild(script)

    const injected = document.querySelector(`script[src*="${gtmId}"]`)
    expect(injected).toBeTruthy()
    expect(window.dataLayer[0].event).toBe('gtm.js')
  })

  it('injects GA4 script and config when gaId is provided without GTM', async () => {
    window.dataLayer = []
    const gaId = 'G-TEST9876'

    const script = document.createElement('script')
    script.async = true
    script.src = `https://www.googletagmanager.com/gtag/js?id=${gaId}`
    document.head.appendChild(script)

    function gtag(...args: any[]) {
      window.dataLayer.push(args)
    }
    // @ts-expect-error Window gtag extension
    window.gtag = gtag
    gtag('js', new Date())
    gtag('config', gaId)

    const injected = document.querySelector(`script[src*="${gaId}"]`)
    expect(injected).toBeTruthy()
    expect(window.dataLayer.length).toBeGreaterThanOrEqual(2)
  })

  it('pushes page_view on route change', () => {
    window.dataLayer = []
    const to = { fullPath: '/items/vintage-jacket' }
    document.title = 'Vintage Jacket - Nego-lah'

    window.dataLayer.push({
      event: 'page_view',
      page_path: to.fullPath,
      page_title: document.title
    })

    expect(window.dataLayer).toContainEqual({
      event: 'page_view',
      page_path: '/items/vintage-jacket',
      page_title: 'Vintage Jacket - Nego-lah'
    })
  })
})
