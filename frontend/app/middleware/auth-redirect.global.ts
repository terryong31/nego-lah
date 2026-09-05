/**
 * Global middleware that catches `?code=...` or `?token_hash=...` query params
 * on ANY page (such as the homepage when redirected from Supabase email verification)
 * and redirects to the dedicated `/confirm` page so users always see the
 * "Email Confirmed" confirmation screen.
 */
export default defineNuxtRouteMiddleware((to) => {
  // Already on /confirm — let the page handle the UI
  if (to.path === '/confirm') return

  const windowSearch = typeof window !== 'undefined' ? window.location.search : ''
  const windowHash = typeof window !== 'undefined' ? window.location.hash : ''

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

  const hash = to.hash || (typeof window !== 'undefined' && window.location.hash ? window.location.hash : undefined)

  return navigateTo({
    path: '/confirm',
    query: to.query,
    ...(hash ? { hash } : {})
  })
})
