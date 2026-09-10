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
  // gtag.js's own command processor only recognizes dataLayer entries shaped
  // exactly like the native `arguments` object — it tags each one it handles
  // with a `gtm.uniqueEventId` once processed. A rest-params array (`[...args]`)
  // looks close enough to read but is never tagged, so every `gtag(...)` call
  // below (consent/js/config) silently no-ops: confirmed by pushing `arguments`
  // instead in an isolated page with the same measurement ID, which fixed it.
  function gtag(..._args: any[]) {
    // eslint-disable-next-line prefer-rest-params
    dataLayer.push(arguments)
  }
  window.gtag = gtag

  // Google can ship a region-based default-denied Consent Mode policy inside
  // the remote config for a measurement ID: the tag then fully initializes
  // (processes `config`, fires its internal load lifecycle) but silently
  // drops every hit until the page sends its own consent signal. Nego-lah has
  // no consent gate (Malaysia-only marketplace, no GDPR/UK exposure), so
  // grant explicitly instead of leaving the default ambiguous.
  gtag('consent', 'default', {
    ad_storage: 'granted',
    ad_user_data: 'granted',
    ad_personalization: 'granted',
    analytics_storage: 'granted'
  })

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

    gtag('js', new Date())
    gtag('config', gaId)
  }

  // Track SPA route changes. `config` (or GTM's own load) already reports the
  // first page, so only re-report on navigations *after* that one — Vue
  // Router's afterEach also fires for the initial route, and re-issuing
  // `config` on every navigation is no longer Google's recommended SPA
  // pattern (it can produce duplicate/conflicting sessions); an `event` is.
  const router = useRouter()
  let isFirstNavigation = true
  router.afterEach((to) => {
    if (isFirstNavigation) {
      isFirstNavigation = false
      return
    }
    gtag('event', 'page_view', {
      page_path: to.fullPath,
      // `afterEach` is queued, so it can run after the document has gone —
      // during teardown in a test environment, or a navigation racing unload.
      // A missing title is worth losing; an unhandled rejection out of an
      // analytics hook is not.
      page_title: typeof document === 'undefined' ? undefined : document.title
    })
  })
})
