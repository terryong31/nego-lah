// Admin API client. Talks ONLY to the FastAPI admin prefix and relies on the
// httpOnly admin cookie (credentials: 'include') — it never touches the Supabase
// client, so the admin session stays isolated from any visitor session.
//
// CSRF: the backend sets a non-httpOnly "csrf_token" cookie on login. We read it
// and echo it back as the X-CSRF-Token header on every request. The backend
// verifies the header matches the server-side token (double-submit cookie pattern).
export const useAdminApi = () => {
  const config = useRuntimeConfig()
  const base = `${config.public.apiBaseUrl}/admin`

  function getCsrfToken(): string {
    if (import.meta.server) return ''
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
    return match ? decodeURIComponent(match[1]) : ''
  }

  const call = <T>(path: string, opts?: Parameters<typeof $fetch>[1]) =>
    $fetch<T>(`${base}${path}`, {
      credentials: 'include',
      ...opts,
      headers: {
        'X-CSRF-Token': getCsrfToken(),
        ...opts?.headers
      }
    })

  return { call }
}
