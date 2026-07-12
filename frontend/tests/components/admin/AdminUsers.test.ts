import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import AdminUsers from '~/components/admin/AdminUsers.vue'

const { callMock, toastAddMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

interface AdminUser {
  id: string
  email: string
  display_name: string
  avatar_url?: string
  is_banned: boolean
  ai_enabled: boolean
  admin_intervening: boolean
  created_at: string
}

function makeUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: 'u1',
    email: 'alice@example.com',
    display_name: 'Alice',
    avatar_url: undefined,
    is_banned: false,
    ai_enabled: true,
    admin_intervening: false,
    created_at: '2026-01-15T00:00:00Z',
    ...overrides
  }
}

// Deferred promise helper for controlling exactly when an awaited call resolves,
// so we can inspect optimistic/in-flight state before it settles.
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

// Loose typing for reaching into <script setup> internals via wrapper.vm.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type VmAny = Record<string, any>

describe('components/admin/AdminUsers.vue', () => {
  // The "nuxt" test environment reuses a single Nuxt app instance across all
  // tests in this file, so useAsyncData's cache for the 'admin-users' key
  // (and its `status`) persists between mountSuspended() calls unless we
  // clear it — otherwise a later mount would silently reuse an earlier
  // test's cached data/status and skip re-invoking `call()` entirely. We also
  // explicitly unmount after every test so each test's component instance
  // fully releases its subscription to that shared cache before the next
  // test's clearNuxtData() call runs (otherwise a still-mounted instance from
  // a prior test can get scheduled for a stray re-render against data that's
  // being reset out from under it).
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    clearNuxtData('admin-users')
  })

  afterEach(async () => {
    wrapper?.unmount()
    wrapper = undefined
    // Let the pending microtask that useAsyncData's internal `_off()` cleanup
    // schedules on unmount run to completion now, while the Nuxt app/component
    // context is still alive, instead of letting it fire later (e.g. during
    // the next test or environment teardown) as an unhandled rejection.
    await flushPromises()
    await nextTick()
  })

  it('fetches /users on mount and renders the user count and rows', async () => {
    callMock.mockResolvedValueOnce([makeUser()])
    wrapper = await mountSuspended(AdminUsers)

    expect(callMock).toHaveBeenCalledWith('/users')
    expect(wrapper.text()).toContain('1 user(s)')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('alice@example.com')
  })

  it('falls back to the empty default state when the initial fetch rejects', async () => {
    callMock.mockRejectedValueOnce(new Error('network down'))
    wrapper = await mountSuspended(AdminUsers)

    expect(wrapper.text()).toContain('0 user(s)')
    expect((wrapper.vm as VmAny).users).toEqual([])
  })

  it('renders a "Banned" badge for banned users and "Active" for active users', async () => {
    callMock.mockResolvedValueOnce([
      makeUser({ id: 'u1', display_name: 'Alice', is_banned: true }),
      makeUser({ id: 'u2', display_name: 'Bob', email: 'bob@example.com', is_banned: false })
    ])
    wrapper = await mountSuspended(AdminUsers)

    expect(wrapper.text()).toContain('Banned')
    expect(wrapper.text()).toContain('Active')
  })

  describe('formatDate', () => {
    it('formats an ISO date string using en-MY locale formatting', async () => {
      callMock.mockResolvedValueOnce([makeUser()])
      wrapper = await mountSuspended(AdminUsers)
      expect((wrapper.vm as VmAny).formatDate('2026-01-15T00:00:00Z')).toBe(
        new Date('2026-01-15T00:00:00Z').toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' })
      )
    })

    it('returns "-" for a falsy date', async () => {
      callMock.mockResolvedValueOnce([makeUser()])
      wrapper = await mountSuspended(AdminUsers)
      expect((wrapper.vm as VmAny).formatDate('')).toBe('-')
    })
  })

  describe('toggleBan', () => {
    it('bans an active user, flips state only after success, and shows a success toast', async () => {
      const user = makeUser({ is_banned: false })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      callMock.mockResolvedValueOnce({})
      await vm.toggleBan(target)

      expect(callMock).toHaveBeenCalledWith('/users/u1/ban', { method: 'PUT', body: { is_banned: true } })
      expect(target.is_banned).toBe(true)
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'User banned', color: 'success' })
      expect(vm.busy).toBeNull()
    })

    it('unbans a banned user and shows the "User unbanned" toast', async () => {
      const user = makeUser({ is_banned: true })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      callMock.mockResolvedValueOnce({})
      await vm.toggleBan(target)

      expect(callMock).toHaveBeenCalledWith('/users/u1/ban', { method: 'PUT', body: { is_banned: false } })
      expect(target.is_banned).toBe(false)
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'User unbanned', color: 'success' })
    })

    it('sets busy to the user id while the request is in flight, then clears it', async () => {
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      const { promise, resolve } = deferred<object>()
      callMock.mockImplementationOnce(() => promise)

      const pending = vm.toggleBan(target)
      expect(vm.busy).toBe('u1')

      resolve({})
      await pending

      expect(vm.busy).toBeNull()
    })

    it('does NOT flip is_banned and shows an error toast (with API detail) when the request fails', async () => {
      const user = makeUser({ is_banned: false })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      callMock.mockRejectedValueOnce({ data: { detail: 'Cannot ban an admin' } })
      await vm.toggleBan(target)

      expect(target.is_banned).toBe(false)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Action failed',
        description: 'Cannot ban an admin',
        color: 'error'
      })
      expect(vm.busy).toBeNull()
    })

    it('falls back to err.message when the failed request has no detail', async () => {
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      callMock.mockRejectedValueOnce(new Error('server exploded'))
      await vm.toggleBan(target)

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Action failed',
        description: 'server exploded',
        color: 'error'
      })
    })
  })

  describe('toggleAi (optimistic update)', () => {
    it('flips ai_enabled immediately, before the request resolves', async () => {
      const user = makeUser({ ai_enabled: true })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      const { promise, resolve } = deferred<object>()
      callMock.mockImplementationOnce(() => promise)

      const pending = vm.toggleAi(target)
      // Flipped synchronously, before the PUT call has settled.
      expect(target.ai_enabled).toBe(false)

      resolve({})
      await pending

      expect(callMock).toHaveBeenCalledWith('/users/u1/ai', { method: 'PUT', body: { ai_enabled: false } })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'AI disabled', color: 'success' })
      expect(target.ai_enabled).toBe(false)
    })

    it('shows "AI enabled" when toggling from disabled to enabled and succeeding', async () => {
      const user = makeUser({ ai_enabled: false })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      callMock.mockResolvedValueOnce({})
      await vm.toggleAi(target)

      expect(target.ai_enabled).toBe(true)
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'AI enabled', color: 'success' })
    })

    it('reverts the optimistic flip and shows an error toast when the request fails', async () => {
      const user = makeUser({ ai_enabled: true })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      const { promise, reject } = deferred<object>()
      callMock.mockImplementationOnce(() => promise)

      const pending = vm.toggleAi(target)
      expect(target.ai_enabled).toBe(false) // optimistic flip applied immediately

      reject({ data: { detail: 'AI toggle blocked' } })
      await pending

      expect(target.ai_enabled).toBe(true) // reverted back to original
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Action failed',
        description: 'AI toggle blocked',
        color: 'error'
      })
    })

    it('falls back to err.message on failure when there is no API detail', async () => {
      const user = makeUser({ ai_enabled: true })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      callMock.mockRejectedValueOnce(new Error('timeout'))
      await vm.toggleAi(target)

      expect(target.ai_enabled).toBe(true)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Action failed',
        description: 'timeout',
        color: 'error'
      })
    })
  })

  describe('edit profile modal (openEdit / saveProfile)', () => {
    it('openEdit populates the form from the user and opens the modal', async () => {
      const user = makeUser({ display_name: 'Alice', avatar_url: 'https://example.com/a.png' })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      vm.openEdit(target)
      await wrapper.vm.$nextTick()

      expect(vm.editOpen).toBe(true)
      expect(vm.editing.id).toBe(target.id)
      expect(vm.form.display_name).toBe('Alice')
      expect(vm.form.avatar_url).toBe('https://example.com/a.png')
    })

    it('openEdit defaults display_name/avatar_url to empty strings when missing', async () => {
      const user = makeUser({ display_name: '', avatar_url: undefined })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      vm.openEdit(vm.users[0])

      expect(vm.form.display_name).toBe('')
      expect(vm.form.avatar_url).toBe('')
    })

    it('is a no-op when editing is null', async () => {
      callMock.mockResolvedValueOnce([makeUser()])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      await vm.saveProfile()

      // Only the initial GET /users call happened - no PUT was issued.
      expect(callMock).toHaveBeenCalledTimes(1)
    })

    it('saves changes: PUTs the profile, mutates the user, shows a success toast, and closes the modal', async () => {
      const user = makeUser({ display_name: 'Old Name', avatar_url: 'https://old.example.com/a.png' })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      vm.openEdit(target)
      vm.form.display_name = 'New Name'
      vm.form.avatar_url = 'https://new.example.com/a.png'

      callMock.mockResolvedValueOnce({})
      await vm.saveProfile()

      expect(callMock).toHaveBeenCalledWith('/users/u1/profile', {
        method: 'PUT',
        body: { display_name: 'New Name', avatar_url: 'https://new.example.com/a.png' }
      })
      expect(target.display_name).toBe('New Name')
      expect(target.avatar_url).toBe('https://new.example.com/a.png')
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'Profile updated', color: 'success' })
      expect(vm.editOpen).toBe(false)
      expect(vm.saving).toBe(false)
    })

    it('sends null and unsets avatar_url when the avatar URL field is cleared', async () => {
      const user = makeUser({ avatar_url: 'https://old.example.com/a.png' })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      const target = vm.users[0]

      vm.openEdit(target)
      vm.form.avatar_url = ''

      callMock.mockResolvedValueOnce({})
      await vm.saveProfile()

      expect(callMock).toHaveBeenCalledWith('/users/u1/profile', {
        method: 'PUT',
        body: { display_name: 'Alice', avatar_url: null }
      })
      expect(target.avatar_url).toBeUndefined()
    })

    it('sets saving to true while the request is in flight, then false', async () => {
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      vm.openEdit(vm.users[0])

      const { promise, resolve } = deferred<object>()
      callMock.mockImplementationOnce(() => promise)

      const pending = vm.saveProfile()
      expect(vm.saving).toBe(true)

      resolve({})
      await pending

      expect(vm.saving).toBe(false)
    })

    it('shows an error toast and keeps the modal open when the update fails', async () => {
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      vm.openEdit(vm.users[0])

      callMock.mockRejectedValueOnce({ data: { detail: 'Name is invalid' } })
      await vm.saveProfile()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Update failed',
        description: 'Name is invalid',
        color: 'error'
      })
      expect(vm.editOpen).toBe(true)
      expect(vm.saving).toBe(false)
    })

    it('falls back to err.message on failure when there is no API detail', async () => {
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny
      vm.openEdit(vm.users[0])

      callMock.mockRejectedValueOnce(new Error('boom'))
      await vm.saveProfile()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Update failed',
        description: 'boom',
        color: 'error'
      })
    })
  })

  describe('remove', () => {
    it('does nothing when window.confirm returns false', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
      const user = makeUser({ display_name: 'Alice', email: 'alice@example.com' })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      await vm.remove(vm.users[0])

      expect(confirmSpy).toHaveBeenCalledWith('Delete Alice? This permanently removes their account and chats.')
      // Only the initial GET /users call happened - no DELETE was issued.
      expect(callMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('falls back to the email in the confirm message when display_name is missing', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
      const user = makeUser({ display_name: '', email: 'noname@example.com' })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      await vm.remove(vm.users[0])

      expect(window.confirm).toHaveBeenCalledWith('Delete noname@example.com? This permanently removes their account and chats.')
    })

    it('deletes, shows a success toast, and refreshes the list when confirmed', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const user = makeUser()
      callMock.mockResolvedValueOnce([user]) // initial load
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      callMock.mockResolvedValueOnce({}) // DELETE
      callMock.mockResolvedValueOnce([]) // refresh() after delete

      await vm.remove(vm.users[0])

      expect(callMock).toHaveBeenCalledWith('/users/u1', { method: 'DELETE' })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'User deleted', color: 'success' })
      expect(callMock).toHaveBeenCalledTimes(3)
      expect(vm.busy).toBeNull()
    })

    it('sets busy to the user id while the delete is in flight', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      const { promise, resolve } = deferred<object>()
      callMock.mockImplementationOnce(() => promise) // DELETE
      callMock.mockResolvedValueOnce([user]) // refresh() after delete

      const pending = vm.remove(vm.users[0])
      expect(vm.busy).toBe('u1')

      resolve({})
      await pending

      expect(vm.busy).toBeNull()
    })

    it('shows an error toast using the API detail message when the DELETE fails', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      callMock.mockRejectedValueOnce({ data: { detail: 'User has active orders' } })
      await vm.remove(vm.users[0])

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Delete failed',
        description: 'User has active orders',
        color: 'error'
      })
      expect(vm.busy).toBeNull()
    })

    it('falls back to err.message when the DELETE error has no detail', async () => {
      vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
      const user = makeUser()
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)
      const vm = wrapper.vm as VmAny

      callMock.mockRejectedValueOnce(new Error('server exploded'))
      await vm.remove(vm.users[0])

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Delete failed',
        description: 'server exploded',
        color: 'error'
      })
    })
  })

  // These exercise the actual template bindings (the compiled inline
  // `@click`/`@update:model-value` handlers) by dispatching real DOM events,
  // rather than calling the underlying <script setup> functions directly -
  // the two are distinct code paths for coverage purposes.
  //
  // Note: the edit-profile <UModal>'s #body/#footer slot content (the form
  // inputs, Cancel and Save buttons) is portalled via <Teleport> by Nuxt
  // UI/Reka UI. mountSuspended() here mounts the bare component (no <UApp>
  // root, which is what normally supplies the teleport target/providers in
  // the real app), so that content never actually mounts - confirmed by
  // checking `wrapper.findAllComponents({ name: undefined })` and
  // `document.body.innerHTML` after opening the modal, neither of which
  // contain the modal's inner form/buttons. Those bindings are therefore not
  // reachable via DOM interaction in this harness (same limitation
  // documented in tests/pages/profile.test.ts for its own delete-account
  // modal), so they're left untested here.
  describe('rendered template bindings (DOM interactions)', () => {
    it('clicking the Refresh button re-fetches /users', async () => {
      callMock.mockResolvedValueOnce([makeUser({ display_name: 'Alice' })])
      wrapper = await mountSuspended(AdminUsers)

      const refreshButton = wrapper.findAll('button').find(b => b.text().includes('Refresh'))
      expect(refreshButton).toBeTruthy()

      callMock.mockResolvedValueOnce([makeUser({ display_name: 'Alice Updated' })])
      await refreshButton!.trigger('click')
      await flushPromises()
      await nextTick()
      await flushPromises()
      await nextTick()

      expect(callMock).toHaveBeenCalledTimes(2)
      expect(callMock).toHaveBeenNthCalledWith(2, '/users')
      // The refresh replaces useAsyncData's underlying `users` state; we assert
      // against the vm's reactive state rather than the rendered DOM text
      // because UTable (tanstack-table under the hood) does not synchronously
      // reflect a full array replacement into `wrapper.text()` within this
      // harness's flush/tick cycle.
      expect((wrapper.vm as VmAny).users[0].display_name).toBe('Alice Updated')
    })

    it('clicking the AI switch in the table row triggers toggleAi via @update:model-value', async () => {
      const user = makeUser({ ai_enabled: true })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)

      const aiSwitch = wrapper.find('button[role="switch"]')
      expect(aiSwitch.exists()).toBe(true)

      callMock.mockResolvedValueOnce({})
      await aiSwitch.trigger('click')
      await flushPromises()
      await nextTick()

      expect(callMock).toHaveBeenCalledWith('/users/u1/ai', { method: 'PUT', body: { ai_enabled: false } })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'AI disabled', color: 'success' })
      expect((wrapper.vm as VmAny).users[0].ai_enabled).toBe(false)
    })

    it('clicking the pencil (edit) button in the table row triggers openEdit via @click', async () => {
      const user = makeUser({ display_name: 'Alice', avatar_url: 'https://example.com/a.png' })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)

      const editButton = wrapper.findAll('button').find(b => b.html().includes('i-lucide:pencil'))
      expect(editButton).toBeTruthy()

      await editButton!.trigger('click')
      await nextTick()

      const vm = wrapper.vm as VmAny
      expect(vm.editOpen).toBe(true)
      expect(vm.editing.id).toBe('u1')
      expect(vm.form.display_name).toBe('Alice')
      expect(vm.form.avatar_url).toBe('https://example.com/a.png')
    })

    it('clicking the Ban button in the table row triggers toggleBan via @click', async () => {
      const user = makeUser({ is_banned: false })
      callMock.mockResolvedValueOnce([user])
      wrapper = await mountSuspended(AdminUsers)

      const banButton = wrapper.findAll('button').find(b => b.text() === 'Ban')
      expect(banButton).toBeTruthy()

      callMock.mockResolvedValueOnce({})
      await banButton!.trigger('click')
      await flushPromises()
      await nextTick()

      expect(callMock).toHaveBeenCalledWith('/users/u1/ban', { method: 'PUT', body: { is_banned: true } })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'User banned', color: 'success' })
      expect((wrapper.vm as VmAny).users[0].is_banned).toBe(true)
    })

    it('clicking the trash (delete) button in the table row triggers remove via @click', async () => {
      const user = makeUser()
      callMock.mockResolvedValueOnce([user]) // initial load
      wrapper = await mountSuspended(AdminUsers)

      const deleteButton = wrapper.findAll('button').find(b => b.html().includes('i-lucide:trash-2'))
      expect(deleteButton).toBeTruthy()

      callMock.mockResolvedValueOnce({}) // DELETE
      callMock.mockResolvedValueOnce([]) // refresh() after delete
      await deleteButton!.trigger('click')
      await flushPromises()
      await nextTick()

      // window.confirm defaults to true (tests/setup.ts).
      expect(callMock).toHaveBeenCalledWith('/users/u1', { method: 'DELETE' })
      expect(toastAddMock).toHaveBeenCalledWith({ title: 'User deleted', color: 'success' })
      expect((wrapper.vm as VmAny).busy).toBeNull()
    })
  })
})
