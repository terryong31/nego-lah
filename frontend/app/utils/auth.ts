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

export interface AvatarUserLike {
  user_metadata?: {
    custom_avatar_url?: string | null
    avatar_url?: string | null
  } | null
}

/**
 * The avatar to display for a user.
 *
 * Supabase re-syncs `user_metadata` from the identity provider's claims on every
 * OAuth sign-in, and Google's claims include `avatar_url`. Anything we wrote
 * there would therefore be replaced by the Google photo the next time the user
 * signs in with Google — so a self-uploaded avatar is stored under
 * `custom_avatar_url` (a key no provider writes) and takes precedence here.
 * `PUT /user/{id}/profile` is the only writer of that key.
 */
export function resolveAvatarUrl(user: AvatarUserLike | null | undefined): string | undefined {
  const meta = user?.user_metadata
  return meta?.custom_avatar_url || meta?.avatar_url || undefined
}

export interface UserIdLike {
  sub?: string | null
  id?: string | null
}

/**
 * The signed-in user's id, from whichever shape the caller happens to hold.
 *
 * `useAuth()`'s `user` carries `id`, and since SPEC-093 that is the only shape
 * this app produces. `sub` is still accepted because that is where the id lived
 * while the session was a Supabase JWT read client-side: `useSupabaseUser()` was
 * populated from `getClaims()`, whose `RequiredClaims` is
 * `{iss, sub, aud, exp, iat, role, aal, session_id}` with no `id` on it at all.
 * Reading `.id` off one of those yielded `undefined` and typechecked anyway,
 * because `JwtPayload` declares `[key: string]: any` — so every guard written as
 * `if (!user.value?.id)` failed shut, and the SSE stream never opened. Keeping
 * both spellings here is what makes that class of bug impossible to reintroduce
 * from either direction.
 */
export function resolveUserId(user: UserIdLike | null | undefined): string | null {
  return user?.sub ?? user?.id ?? null
}

/**
 * Read a cookie the browser will let JavaScript see.
 *
 * Only the CSRF tokens qualify: the session cookies (`nl_sid`, `admin_sid`) are
 * httpOnly and will never appear here, which is the entire point of SPEC-093.
 */
export function readCookie(name: string): string {
  if (typeof document === 'undefined') return ''
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`))
  return (match && match[1]) ? decodeURIComponent(match[1]) : ''
}

/** The buyer session's CSRF token, echoed back on every mutating request. */
export function getUserCsrfToken(): string {
  return readCookie('nl_csrf')
}
