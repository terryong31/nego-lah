export interface RouteLike {
  path: string
  meta?: Record<string, unknown>
  matched?: Array<{ meta?: Record<string, unknown> }>
}

/**
 * Determines whether a given route is auth-guarded (requires authentication).
 * Checks route middleware definitions ('auth' | 'admin-auth'), matched records,
 * and known protected route prefixes (/orders, /chat, /profile, /_console/*).
 */
export function isAuthGuarded(route: RouteLike): boolean {
  if (!route) return false

  const hasAuthMiddleware = (meta?: Record<string, unknown>): boolean => {
    if (!meta) return false
    const mw = meta.middleware
    if (typeof mw === 'string') {
      return mw === 'auth' || mw === 'admin-auth'
    }
    if (Array.isArray(mw)) {
      return mw.includes('auth') || mw.includes('admin-auth')
    }
    return false
  }

  // 1. Check current route's own meta
  if (hasAuthMiddleware(route.meta)) {
    return true
  }

  // 2. Check matched route records (for nested routes/layouts)
  if (route.matched?.some(record => hasAuthMiddleware(record.meta))) {
    return true
  }

  // 3. Fallback check for known protected path prefixes
  const cleanPath = (route.path || '').split('?')[0]!.split('#')[0]!
  const protectedPrefixes = ['/orders', '/chat', '/profile', '/_console']
  if (cleanPath === '/_console/login') {
    return false
  }

  return protectedPrefixes.some(
    prefix => cleanPath === prefix || cleanPath.startsWith(`${prefix}/`)
  )
}

// Pages there is no point returning a visitor to after they sign in: the
// homepage is the default anyway, and bouncing them back onto an auth screen
// would loop them straight through it.
const NO_RETURN_PATHS = ['/', '/login', '/register', '/forgot-password', '/reset-password', '/confirm']

/**
 * Normalises a candidate post-login return target. Only same-origin paths pass —
 * an absolute URL or a protocol-relative `//evil.com` would turn `/login` into an
 * open redirect, since the value reaches us from a query string or a cookie.
 */
export function safeRedirectPath(value: unknown): string | null {
  if (typeof value !== 'string') return null
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return null
  return value
}

/**
 * The `/login` target to bounce an unauthenticated visitor to, carrying the page
 * they were on so they land back on it after signing in — including its query
 * string, which is what keeps `/chat?item_id=…` pointed at the right negotiation.
 *
 * Every bounce to `/login` goes through here (route middleware, the `useApi` 401
 * interceptor, the chat send guard, the item page's Buy button) so the safe-path
 * check lives in exactly one place.
 */
export function loginRedirect(fullPath?: string | null): { path: string, query?: { redirect: string } } {
  const target = safeRedirectPath(fullPath)
  if (!target) return { path: '/login' }

  const cleanPath = target.split('?')[0]!.split('#')[0]!
  if (NO_RETURN_PATHS.includes(cleanPath)) return { path: '/login' }

  return { path: '/login', query: { redirect: target } }
}
