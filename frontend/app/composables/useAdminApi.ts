// Admin API client. Talks ONLY to the FastAPI admin prefix and relies on the
// httpOnly admin cookie (credentials: 'include') — it never touches the Supabase
// client, so the admin session stays isolated from any visitor session.
export const useAdminApi = () => {
  const config = useRuntimeConfig()
  const base = `${config.public.apiBaseUrl}/admin`

  const call = <T>(path: string, opts?: Parameters<typeof $fetch>[1]) =>
    $fetch<T>(`${base}${path}`, {
      credentials: 'include',
      ...opts
    })

  return { call }
}
