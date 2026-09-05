/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    dataLayer: Record<string, any>[]
    gtag?: (...args: any[]) => void
  }
}

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const gtmId = (config.public.gtmId as string) || ''
  const gaId = (config.public.gaId as string) || ''

  if (!gtmId && !gaId) return

  // Setup dataLayer for Google services
  const dataLayer = (window.dataLayer = window.dataLayer || [])

  // Initialize GTM
  if (gtmId) {
    dataLayer.push({
      'gtm.start': new Date().getTime(),
      'event': 'gtm.js'
    })
    const script = document.createElement('script')
    script.async = true
    script.src = `https://www.googletagmanager.com/gtm.js?id=${gtmId}`
    document.head.appendChild(script)
  } else if (gaId) {
    // Standalone GA4 if GTM is not present
    const script = document.createElement('script')
    script.async = true
    script.src = `https://www.googletagmanager.com/gtag/js?id=${gaId}`
    document.head.appendChild(script)

    function gtag(...args: any[]) {
      dataLayer.push(args)
    }
    window.gtag = gtag
    gtag('js', new Date())
    gtag('config', gaId)
  }

  // Track SPA route changes
  const router = useRouter()
  router.afterEach((to) => {
    dataLayer.push({
      event: 'page_view',
      page_path: to.fullPath,
      page_title: document.title
    })
    if (window.gtag && gaId) {
      window.gtag('config', gaId, {
        page_path: to.fullPath,
        page_title: document.title
      })
    }
  })
})
