// Gate the /_console admin pages. The admin session lives in an httpOnly cookie
// on the API host, so we verify it client-side against the backend.
export default defineNuxtRouteMiddleware(async () => {
  if (import.meta.server) return

  const { call } = useAdminApi()
  try {
    await call('/auth/session')
  } catch {
    return navigateTo('/_console/login')
  }
})
