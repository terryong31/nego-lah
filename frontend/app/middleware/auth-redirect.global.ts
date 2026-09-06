/**
 * Global middleware that catches `?code=...` or `?token_hash=...` query params
 * on ANY page (such as the homepage when redirected from Supabase email verification)
 * and redirects to the dedicated `/confirm` page so users always see the
 * "Email Confirmed" confirmation screen.
 */
export default defineNuxtRouteMiddleware((to, from) => {
  // Already on /confirm — let the page handle the UI
  if (to.path === '/confirm') return

  // Leaving /confirm is the callback page handing control back to the app once
  // the session is established. The browser URL still reads `/confirm?code=...`
  // until this navigation commits, so re-inspecting it below would send the
  // visitor straight back and strand them on the "Confirming your session"
  // spinner — signed in, but unable to leave the callback route.
  if (from.path === '/confirm') return

  // `window.location` describes `to` only on the SPA's very first navigation,
  // where Nuxt calls this middleware with `from` equal to `to`. On any later
  // in-app navigation it still points at the page being left, so consulting it
  // would redirect on params that belong to a callback already handled.
  const isInitialNavigation = to.fullPath === from.fullPath
  const useWindowUrl = isInitialNavigation && typeof window !== 'undefined'

  const windowSearch = useWindowUrl ? window.location.search : ''
  const windowHash = useWindowUrl ? window.location.hash : ''

  const hasAuthQuery = Boolean(
    to.query.code
    || to.query.token_hash
    || to.query.error
    || to.query.error_code
    || windowSearch.includes('code=')
    || windowSearch.includes('token_hash=')
    || windowSearch.includes('error=')
    || windowSearch.includes('error_code=')
  )

  const hasAuthHash = Boolean(
    (to.hash && (
      to.hash.includes('error=')
      || to.hash.includes('error_code=')
      || to.hash.includes('access_token=')
      || to.hash.includes('code=')
    ))
    || (windowHash && (
      windowHash.includes('error=')
      || windowHash.includes('error_code=')
      || windowHash.includes('access_token=')
      || windowHash.includes('code=')
    ))
  )

  if (!hasAuthQuery && !hasAuthHash) return

  const hash = to.hash || (windowHash || undefined)

  return navigateTo({
    path: '/confirm',
    query: to.query,
    ...(hash ? { hash } : {})
  })
})
