import { getUserCsrfToken } from '~/utils/auth'

/**
 * The buyer's session, as far as the browser is concerned (SPEC-093).
 *
 * There is no token here, and there is no Supabase client. The session is an
 * httpOnly cookie this code cannot read, set by `POST /auth/login` and friends;
 * all this composable holds is who the server says the cookie belongs to, plus
 * the calls that create and destroy it.
 *
 * `user` replaces `useSupabaseUser()`. It is a plain object rather than a JWT
 * payload, so the id is `id` — see `resolveUserId`, which still accepts `sub`
 * for anything that has not been migrated.
 */
/**
 * The keys this app actually reads off `user_metadata`, spelled out so they come
 * back as strings rather than `unknown`. Anything else Supabase or an identity
 * provider writes there is still carried, just untyped.
 */
export interface AuthUserMetadata {
  display_name?: string | null
  avatar_url?: string | null
  custom_avatar_url?: string | null
  preferred_language?: string | null
  [key: string]: unknown
}

export interface AuthUser {
  id: string
  email?: string | null
  user_metadata?: AuthUserMetadata | null
}

export const useAuthUser = () => useState<AuthUser | null>('auth:user', () => null)

/** False until the first `/auth/session` call settles, so guards can wait. */
export const useAuthReady = () => useState<boolean>('auth:ready', () => false)

export function useAuth() {
  const config = useRuntimeConfig()
  const user = useAuthUser()
  const ready = useAuthReady()
  const base = config.public.apiBaseUrl

  /** Ask the server who we are. The only way to learn it — the cookie is opaque. */
  async function fetchSession(): Promise<AuthUser | null> {
    try {
      const res = await $fetch<{ user: AuthUser }>(`${base}/auth/session`, {
        credentials: 'include'
      })
      user.value = res.user
    } catch {
      // 401 is the ordinary answer for a visitor who is not signed in.
      user.value = null
    } finally {
      ready.value = true
    }
    return user.value
  }

  function turnstileHeaders(token?: string | null): Record<string, string> {
    return token ? { 'X-Turnstile-Token': token } : {}
  }

  async function login(email: string, password: string, turnstileToken?: string | null) {
    const res = await $fetch<{ user: AuthUser }>(`${base}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: turnstileHeaders(turnstileToken),
      body: { email, password }
    })
    user.value = res.user
    ready.value = true
    return res.user
  }

  async function register(email: string, password: string, turnstileToken?: string | null) {
    return $fetch<{ confirmation_sent: boolean }>(`${base}/auth/register`, {
      method: 'POST',
      credentials: 'include',
      headers: turnstileHeaders(turnstileToken),
      body: { email, password }
    })
  }

  /**
   * Hand the browser to Supabase for OAuth. A full navigation, not a fetch: the
   * round trip ends at the API's own callback, which sets the cookie and 302s
   * back here. Nothing in this tab ever sees the authorization code.
   */
  function signInWithProvider(provider: 'google', next = '/') {
    const url = new URL(`${base}/auth/oauth/start`)
    url.searchParams.set('provider', provider)
    if (next && next !== '/') url.searchParams.set('next', next)
    window.location.href = url.toString()
  }

  async function logout() {
    try {
      await $fetch(`${base}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': getUserCsrfToken() }
      })
    } finally {
      // Whatever the server said, this browser is done with the session.
      clearSession()
    }
  }

  /** Forget the session locally. Used on sign-out and on any 401. */
  function clearSession() {
    user.value = null
    ready.value = true
  }

  async function forgotPassword(email: string, turnstileToken?: string | null) {
    return $fetch<{ sent: boolean }>(`${base}/auth/password/forgot`, {
      method: 'POST',
      credentials: 'include',
      headers: turnstileHeaders(turnstileToken),
      body: { email }
    })
  }

  /** Set a new password using the recovery session the email link established. */
  async function resetPassword(newPassword: string) {
    return $fetch<{ updated: boolean }>(`${base}/auth/password/reset`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Token': getUserCsrfToken() },
      body: { new_password: newPassword }
    })
  }

  return {
    user,
    ready,
    fetchSession,
    login,
    register,
    signInWithProvider,
    logout,
    clearSession,
    forgotPassword,
    resetPassword
  }
}
