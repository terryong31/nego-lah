/**
 * Establish who is signed in before the first route guard runs.
 *
 * The session is an httpOnly cookie, so nothing on the client can read it — the
 * only way to know whether this browser has one is to ask. `enforce: 'pre'`
 * plus the await means `middleware/auth` and every page see a settled answer
 * rather than a null that means "not asked yet" (SPEC-093).
 *
 * This is the plugin `@nuxtjs/supabase` used to provide.
 */
export default defineNuxtPlugin({
  name: 'auth-session',
  enforce: 'pre',
  async setup() {
    const { fetchSession } = useAuth()
    await fetchSession()
  }
})
