import { loginRedirect } from '~/utils/auth'

/**
 * `reauth: true` marks a call whose 401 means "the password you just typed is
 * wrong" rather than "your session is dead" — the account endpoints that demand
 * `current_password` (SPEC-056 #3/#7). Without it, mistyping your password on
 * the profile page would sign you out of a session that was never in question.
 * A banned 403 still signs out either way.
 */
type CallOptions = Parameters<typeof $fetch>[1] & { reauth?: boolean }

export const useApi = () => {
  const supabase = useSupabaseClient()
  const config = useRuntimeConfig()
  const toast = useToast()
  // Read reactively at failure time, not at composable-creation time, so the
  // bounce carries whatever page the caller is actually sitting on.
  const route = useRoute()

  const call = async <T>(path: string, opts?: CallOptions) => {
    const { reauth, ...fetchOpts } = opts ?? {}
    const { data: { session } } = await supabase.auth.getSession()
    const { token: turnstileToken } = useTurnstileToken()

    return $fetch<T>(`${config.public.apiBaseUrl}${path}`, {
      ...fetchOpts,
      headers: {
        ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
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

        // 401 = the token is missing/expired/invalid (e.g. a stale session left
        // over from switching accounts). 403 banned = the backend now blocks the
        // account on every request. Either way the local Supabase session is
        // useless, so sign out and bounce to login instead of leaving the user
        // stuck on a dead app — carrying the current page so signing back in
        // returns them to it (a lapsed session mid-negotiation on /chat is the
        // case that matters).
        if ((response.status === 401 && !reauth) || isBanned) {
          if (isBanned) {
            toast.add({ title: 'Account suspended', description: 'Your account has been banned.', color: 'error' })
          }
          await supabase.auth.signOut()
          await navigateTo(loginRedirect(route.fullPath))
        }
      }
    })
  }

  return { call }
}
