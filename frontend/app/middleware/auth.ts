import { loginRedirect } from '~/utils/auth'

export default defineNuxtRouteMiddleware(async (to) => {
  const { user, ready, fetchSession } = useAuth()

  // `plugins/auth.client.ts` settles this before the first navigation, so this
  // is a fallback for the cases it cannot cover — a hard refresh racing the
  // plugin, or a session that lapsed while the tab sat open.
  if (!ready.value) {
    await fetchSession()
  }

  if (!user.value) {
    return navigateTo(loginRedirect(to?.fullPath))
  }
})
