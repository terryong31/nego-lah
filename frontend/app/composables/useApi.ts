import { getUserCsrfToken, loginRedirect } from '~/utils/auth'

/**
 * `reauth: true` marks a call whose 401 means "the password you just typed is
 * wrong" rather than "your session is dead" — the account endpoints that demand
 * `current_password` (SPEC-056 #3/#7). Without it, mistyping your password on
 * the profile page would sign you out of a session that was never in question.
 * A banned 403 still signs out either way.
 */
type CallOptions = Parameters<typeof $fetch>[1] & { reauth?: boolean }

export const useApi = () => {
  const config = useRuntimeConfig()
  const toast = useToast()
  const { clearSession } = useAuth()
  // Read reactively at failure time, not at composable-creation time, so the
  // bounce carries whatever page the caller is actually sitting on.
  const route = useRoute()

  const call = async <T>(path: string, opts?: CallOptions) => {
    const { reauth, ...fetchOpts } = opts ?? {}
    const { token: turnstileToken } = useTurnstileToken()

    return $fetch<T>(`${config.public.apiBaseUrl}${path}`, {
      ...fetchOpts,
      // SPEC-093: the session is an httpOnly cookie on the API host. There is no
      // Authorization header to attach any more — and no token in this page for
      // an injected script to find. `credentials: 'include'` is what carries it
      // cross-origin; the CSRF token below is what stops another origin from
      // riding along on it.
      credentials: 'include',
      headers: {
        'X-CSRF-Token': getUserCsrfToken(),
        ...(turnstileToken.value ? { 'X-Turnstile-Token': turnstileToken.value } : {}),
        ...opts?.headers
      },
      async onResponseError({ response }) {
        const detail = (response._data as { detail?: unknown })?.detail
        const isBanned = response.status === 403
          && typeof detail === 'string'
          && detail.toLowerCase().includes('banned')

        if (response.status >= 500) {
          import('@sentry/nuxt').then((Sentry) => {
            Sentry.captureMessage(`Server error ${response.status}: ${path}`, {
              level: 'error',
              extra: { status: response.status, path, data: response._data }
            })
          }).catch(() => {})
        }

        // 401 = the cookie is missing, expired or revoked (a session the server
        // ended, an account switched in another tab). 403 banned = the backend
        // now blocks the account on every request. Either way this browser's
        // session is over, so drop what we know locally and bounce to login —
        // carrying the current page so signing back in returns them to it (a
        // lapsed session mid-negotiation on /chat is the case that matters).
        if ((response.status === 401 && !reauth) || isBanned) {
          if (isBanned) {
            toast.add({ title: 'Account suspended', description: 'Your account has been banned.', color: 'error' })
          }
          clearSession()
          await navigateTo(loginRedirect(route.fullPath))
        }
      }
    })
  }

  return { call }
}
