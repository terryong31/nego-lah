/**
 * Catch an auth link that was minted before SPEC-093 and still points here.
 *
 * Since SPEC-093 the browser never receives `?code=` or `?token_hash=` at all:
 * Supabase redirects to `GET /auth/callback` on the API, which redeems the link
 * server-side and 302s back with a session cookie. Nothing in this app has an
 * exchange to perform any more, and an error from that redirect arrives as
 * `/login?error=`, not as query params on whatever page happened to be open.
 *
 * Links already sitting in inboxes when that shipped still point here, though,
 * and their params land on whatever route was registered as the redirect
 * target — usually the homepage. Rather than letting them fall through to a
 * page that would ignore them, send them to /confirm: a redeemable one is
 * forwarded to the API from there, and an expired one gets the failure screen
 * instead of a silent homepage.
 */
export default defineNuxtRouteMiddleware((to, from) => {
  // Already there, or on the way out of it — re-inspecting the URL a callback
  // just handled would send the visitor straight back.
  if (to.path === '/confirm' || from.path === '/confirm') return

  const hasRedeemableLink = typeof to.query.code === 'string' || typeof to.query.token_hash === 'string'
  const hasAuthError = typeof to.query.error === 'string' || typeof to.query.error_code === 'string'

  // An error from the implicit flow arrives in the fragment, which `to.query`
  // never sees. Only trust `window.location` on the first navigation: on any
  // later one the browser URL still describes the page being left.
  const isInitialNavigation = to.fullPath === from.fullPath
  const hash = to.hash || (isInitialNavigation && typeof window !== 'undefined' ? window.location.hash : '')
  const hasAuthHash = Boolean(hash) && /(?:^|[#&])(error|error_code|access_token|code)=/.test(hash)

  if (!hasRedeemableLink && !hasAuthError && !hasAuthHash) return

  return navigateTo({
    path: '/confirm',
    query: to.query,
    ...(hash ? { hash } : {})
  })
})
