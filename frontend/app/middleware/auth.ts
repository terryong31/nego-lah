import { loginRedirect } from '~/utils/auth'

export default defineNuxtRouteMiddleware(async (to) => {
  const user = useSupabaseUser()
  const supabase = useSupabaseClient()

  let isAuthenticated = Boolean(user.value)
  if (!isAuthenticated) {
    try {
      const { data: { session } } = await supabase.auth.getSession()
      isAuthenticated = Boolean(session?.user)
    } catch {
      isAuthenticated = false
    }
  }

  if (!isAuthenticated) {
    return navigateTo(loginRedirect(to?.fullPath))
  }
})
