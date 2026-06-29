export const useApi = () => {
  const supabase = useSupabaseClient()
  const config = useRuntimeConfig()
  const toast = useToast()

  const call = async <T>(path: string, opts?: Parameters<typeof $fetch>[1]) => {
    const { data: { session } } = await supabase.auth.getSession()

    return $fetch<T>(`${config.public.apiBaseUrl}${path}`, {
      ...opts,
      headers: {
        ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
        ...opts?.headers
      },
      async onResponseError({ response }) {
        const detail = (response._data as { detail?: unknown })?.detail
        const isBanned = response.status === 403
          && typeof detail === 'string'
          && detail.toLowerCase().includes('banned')

        // 401 = the token is missing/expired/invalid (e.g. a stale session left
        // over from switching accounts). 403 banned = the backend now blocks the
        // account on every request. Either way the local Supabase session is
        // useless, so sign out and bounce to login instead of leaving the user
        // stuck on a dead app.
        if (response.status === 401 || isBanned) {
          if (isBanned) {
            toast.add({ title: 'Account suspended', description: 'Your account has been banned.', color: 'error' })
          }
          await supabase.auth.signOut()
          await navigateTo('/login')
        }
      }
    })
  }

  return { call }
}
