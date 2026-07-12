import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import AppHeader from '~/components/AppHeader.vue'

// A hand-rolled ref-alike (rather than a real `ref()` from 'vue') so this can
// live inside `vi.hoisted` without tripping over Vitest's import-hoisting
// order — Vue's `isRef`/`unref` only check for the `__v_isRef` marker, so this
// still unwraps correctly wherever the template does `v-if="user"`.
const { userRef } = vi.hoisted(() => ({
  userRef: { __v_isRef: true, value: null as Record<string, unknown> | null }
}))
const { signOutMock, toastAddMock } = vi.hoisted(() => ({
  signOutMock: vi.fn(),
  toastAddMock: vi.fn()
}))

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    signOut: signOutMock
  }
}))
mockNuxtImport('useToast', () => () => ({
  add: toastAddMock
}))

// Note: useRouter/useRoute are deliberately left un-mocked. Nuxt's own
// internal client plugins (chunk-reload, navigation-repaint, page view sync,
// ...) also call `useRouter()` for the whole app, and a partial stub (e.g.
// `{ push: vi.fn() }`) breaks them with "router.beforeEach is not a
// function" etc. Instead we drive the real router via mountSuspended's
// `route` option (for isAuthPage) and spy on the real router's `push` method
// (for the dropdown/sign-out actions).

describe('components/AppHeader.vue', () => {
  beforeEach(() => {
    userRef.value = null
    signOutMock.mockReset().mockResolvedValue({ error: null })
    toastAddMock.mockReset()
  })

  describe('isAuthPage', () => {
    // Routes with no `auth` middleware, so an unauthenticated mount doesn't
    // get redirected to /login before we can inspect the resolved route.
    it.each([
      ['/login', true],
      ['/register', true],
      ['/forgot-password', true],
      ['/reset-password', true],
      ['/', false],
      ['/terms', false],
      ['/privacy', false]
    ])('route %s -> isAuthPage %s', async (path, expected) => {
      const wrapper = await mountSuspended(AppHeader, { route: path })
      expect(wrapper.vm.isAuthPage).toBe(expected)
    })
  })

  describe('dropdownItems', () => {
    it('is an empty array when logged out', async () => {
      userRef.value = null
      const wrapper = await mountSuspended(AppHeader)
      expect(wrapper.vm.dropdownItems).toEqual([])
    })

    it('builds 3 groups when logged in: account, nav links, sign out', async () => {
      userRef.value = { email: 'a@b.com', user_metadata: {} }
      const wrapper = await mountSuspended(AppHeader)
      const items = wrapper.vm.dropdownItems as unknown[][]

      expect(items).toHaveLength(3)

      // Group 1: disabled account entry showing the user's email
      expect(items[0]).toEqual([{ label: 'a@b.com', disabled: true }])

      // Group 2: navigation shortcuts
      const navGroup = items[1] as { label: string, icon: string, onSelect: () => void }[]
      expect(navGroup).toHaveLength(3)
      expect(navGroup.map(i => i.label)).toEqual(['Chat', 'My Orders', 'Profile Settings'])
      expect(navGroup.every(i => typeof i.onSelect === 'function')).toBe(true)

      // Group 3: sign out
      const signOutGroup = items[2] as { label: string, onSelect: () => void }[]
      expect(signOutGroup).toHaveLength(1)
      expect(signOutGroup[0].label).toBe('Sign Out')
      expect(typeof signOutGroup[0].onSelect).toBe('function')
    })

    it('falls back to "My Account" when the user has no email', async () => {
      userRef.value = { email: null, user_metadata: {} }
      const wrapper = await mountSuspended(AppHeader)
      const items = wrapper.vm.dropdownItems as { label: string, disabled: boolean }[][]
      expect(items[0][0]).toEqual({ label: 'My Account', disabled: true })
    })

    it('nav item onSelect handlers push to the expected routes', async () => {
      userRef.value = { email: 'a@b.com', user_metadata: {} }
      const wrapper = await mountSuspended(AppHeader)
      const pushSpy = vi.spyOn(wrapper.vm.$router, 'push').mockResolvedValue(undefined)

      const items = wrapper.vm.dropdownItems as { label: string, onSelect: () => void }[][]
      const [, navGroup] = items

      navGroup[0].onSelect()
      expect(pushSpy).toHaveBeenCalledWith('/chat')

      navGroup[1].onSelect()
      expect(pushSpy).toHaveBeenCalledWith('/orders')

      navGroup[2].onSelect()
      expect(pushSpy).toHaveBeenCalledWith('/profile')

      expect(pushSpy).toHaveBeenCalledTimes(3)
    })
  })

  describe('sign out', () => {
    async function mountAndGetSignOut() {
      userRef.value = { email: 'a@b.com', user_metadata: {} }
      const wrapper = await mountSuspended(AppHeader)
      const pushSpy = vi.spyOn(wrapper.vm.$router, 'push').mockResolvedValue(undefined)
      const items = wrapper.vm.dropdownItems as { label: string, onSelect: () => Promise<void> }[][]
      return { onSelect: items[2][0].onSelect, pushSpy }
    }

    it('shows a success toast and redirects home when signOut succeeds', async () => {
      signOutMock.mockResolvedValue({ error: null })
      const { onSelect, pushSpy } = await mountAndGetSignOut()

      await onSelect()

      expect(signOutMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Signed out',
        description: 'See you again!',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith('/')
    })

    it('shows an error toast and does not redirect when signOut fails', async () => {
      signOutMock.mockResolvedValue({ error: { message: 'network down' } })
      const { onSelect, pushSpy } = await mountAndGetSignOut()

      await onSelect()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Logout failed',
        description: 'network down',
        color: 'error'
      })
      expect(pushSpy).not.toHaveBeenCalled()
    })
  })

  describe('rendering', () => {
    it('shows a Login button when logged out and not on an auth page', async () => {
      userRef.value = null
      const wrapper = await mountSuspended(AppHeader, { route: '/' })
      expect(wrapper.text()).toContain('Login')
    })

    it('hides the Login button when logged out on an auth page', async () => {
      userRef.value = null
      const wrapper = await mountSuspended(AppHeader, { route: '/login' })
      expect(wrapper.text()).not.toContain('Login')
    })

    it('renders a personalised greeting for a logged-in user with a display name', async () => {
      userRef.value = { email: 'hello@example.com', user_metadata: { display_name: 'Terry' } }
      const wrapper = await mountSuspended(AppHeader)
      expect(wrapper.text()).toContain('Hello, Terry')
    })

    it('falls back to the email in the greeting when there is no display name', async () => {
      userRef.value = { email: 'hello@example.com', user_metadata: {} }
      const wrapper = await mountSuspended(AppHeader)
      expect(wrapper.text()).toContain('Hello, hello@example.com')
    })
  })
})
