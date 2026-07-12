import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import ProfilePage from '~/pages/profile.vue'

// Loose typing for reaching into <script setup> internals via wrapper.vm.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type VmAny = Record<string, any>

// useSupabaseUser() returns a real Vue ref in the app. A plain object tagged
// with __v_isRef satisfies isRef()/unref() checks (used for `user.value` reads
// and the initial computed/ref defaults) without pulling in full reactivity -
// same pattern as tests/pages/orders.test.ts.
const { userRef } = vi.hoisted(() => ({
  userRef: { __v_isRef: true, value: null as Record<string, unknown> | null }
}))

// The plain object above satisfies isRef()/unref() for one-shot reads, but
// profile.vue also does `watch(user, ...)` to re-sync displayName/avatarUrl
// when the user object changes elsewhere in the app. A real Vue effect only
// re-runs when it can *track* a dependency, which requires an actual get/set
// pair wired through Vue's reactivity (track/trigger) - a plain property
// mutation is invisible to it. Retrofit a real `ref()`'s get/set onto the
// SAME `userRef` object (preserving its identity, so the mock above is
// unaffected) purely so that one watch-focused test below can exercise it;
// every other test only ever reads/writes `.value` before mounting, which
// behaves identically whether or not this wiring is in place.
const reactiveUserBacking = ref<Record<string, unknown> | null>(null)
Object.defineProperty(userRef, 'value', {
  get: () => reactiveUserBacking.value,
  set: (v: Record<string, unknown> | null) => {
    reactiveUserBacking.value = v
  },
  enumerable: true,
  configurable: true
})

const { callMock } = vi.hoisted(() => ({
  callMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

const { getSessionMock, refreshSessionMock, signOutMock } = vi.hoisted(() => ({
  getSessionMock: vi.fn(),
  refreshSessionMock: vi.fn(),
  signOutMock: vi.fn()
}))

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useSupabaseClient', () => () => ({
  auth: {
    getSession: getSessionMock,
    refreshSession: refreshSessionMock,
    signOut: signOutMock
  }
}))
mockNuxtImport('useApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

function makeFile(name = 'avatar.png', sizeBytes = 1024, type = 'image/png'): File {
  const file = new File(['x'.repeat(Math.min(sizeBytes, 10))], name, { type })
  // jsdom/happy-dom compute `size` from the blob parts; override directly so
  // we can simulate large uploads without actually allocating huge buffers.
  Object.defineProperty(file, 'size', { value: sizeBytes })
  return file
}

function fileChangeEvent(file: File | undefined) {
  return { target: { files: file ? [file] : [] } } as unknown as Event
}

// Note: useRouter is deliberately left un-mocked (see tests/pages/login.test.ts for
// precedent). A partial stub like `{ push: vi.fn() }` breaks Nuxt's own internal
// client plugins which call real router methods during app init. Instead we spy on
// the real router's `push` method per-test via `wrapper.vm.$router`.
function spyOnRouterPush(wrapper: { vm: { $router: { push: (...args: unknown[]) => unknown } } }) {
  return vi.spyOn(wrapper.vm.$router, 'push').mockImplementation(() => Promise.resolve())
}

async function fillAndSubmitEmail(wrapper: VueWrapper, email = 'new@example.com') {
  const emailForm = wrapper.findAll('form')[0]!
  await emailForm.find('input[type="email"]').setValue(email)
  await emailForm.trigger('submit')
  await flushPromises()
}

async function fillAndSubmitPassword(
  wrapper: VueWrapper,
  current = 'password123',
  next = 'newpassword123',
  confirm = next
) {
  const passwordForm = wrapper.findAll('form')[1]!
  const inputs = passwordForm.findAll('input[type="password"]')
  await inputs[0]!.setValue(current)
  await inputs[1]!.setValue(next)
  await inputs[2]!.setValue(confirm)
  await passwordForm.trigger('submit')
  await flushPromises()
}

// Both the Email Address and Security Settings <UForm>s are now bound to a
// reactive `:state` (emailState / passwordState) with each <UInput> wired via
// `v-model`, so real DOM submission validates against Zod and emits `submit`
// correctly. (Previously neither form had `:state`, so `parseAsync(undefined)`
// produced a nameless root Zod error, no <UFormField> surfaced it, and `submit`
// never fired - filling a valid email/password and clicking the button did
// nothing visible. That regression is now covered by the DOM-submission tests
// below.)

describe('pages/profile.vue', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    userRef.value = {
      id: 'reactive-uid',
      email: 'user@example.com',
      user_metadata: { display_name: 'Alice', avatar_url: 'https://example.com/old-avatar.png' }
    }
    callMock.mockReset()
    toastAddMock.mockReset()
    getSessionMock.mockReset().mockResolvedValue({ data: { session: { user: { id: 'session-uid' } } } })
    refreshSessionMock.mockReset().mockResolvedValue({ data: { session: null } })
    signOutMock.mockReset().mockResolvedValue({ error: null })
    // happy-dom's URL.createObjectURL rejects a `File` constructed from this
    // realm's globals with "must be an instance of Blob" in this environment;
    // stub it so onAvatarChange's preview-URL branch is exercised without
    // depending on that cross-realm Blob check. Cleared by the global
    // vi.restoreAllMocks() in tests/setup.ts's afterEach.
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  describe('initial render', () => {
    it('pre-fills display name / avatar from user_metadata and shows the current email', async () => {
      wrapper = await mountSuspended(ProfilePage)

      expect((wrapper.vm as VmAny).displayName).toBe('Alice')
      expect((wrapper.vm as VmAny).avatarUrl).toBe('https://example.com/old-avatar.png')
      expect(wrapper.find('input[disabled]').exists()).toBe(true)
      expect((wrapper.find('input[disabled]').element as HTMLInputElement).value).toBe('user@example.com')
    })

    it('computes initials from the display name', async () => {
      wrapper = await mountSuspended(ProfilePage)
      expect((wrapper.vm as VmAny).initials).toBe('AL')
    })

    it('falls back to the email for initials when there is no display name', async () => {
      userRef.value = { id: 'reactive-uid', email: 'zed@example.com', user_metadata: {} }
      wrapper = await mountSuspended(ProfilePage)
      expect((wrapper.vm as VmAny).initials).toBe('ZE')
    })
  })

  describe('watch(user, ...): re-syncs displayName/avatarUrl when the user object changes elsewhere', () => {
    it('updates displayName and avatarUrl to the new user_metadata when the reactive user changes after mount', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      expect(vm.displayName).toBe('Alice')
      expect(vm.avatarUrl).toBe('https://example.com/old-avatar.png')

      userRef.value = {
        id: 'reactive-uid',
        email: 'bob@example.com',
        user_metadata: { display_name: 'Bob', avatar_url: 'https://example.com/bob.png' }
      }
      await wrapper.vm.$nextTick()
      await flushPromises()

      expect(vm.displayName).toBe('Bob')
      expect(vm.avatarUrl).toBe('https://example.com/bob.png')
    })

    it('falls back to empty strings when the user changes to have no user_metadata', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      userRef.value = { id: 'reactive-uid', email: 'noone@example.com' }
      await wrapper.vm.$nextTick()
      await flushPromises()

      expect(vm.displayName).toBe('')
      expect(vm.avatarUrl).toBe('')
    })

    it('falls back to empty strings when the user changes to null', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      userRef.value = null
      await wrapper.vm.$nextTick()
      await flushPromises()

      expect(vm.displayName).toBe('')
      expect(vm.avatarUrl).toBe('')
    })
  })

  describe('getUserId preference (session over reactive user)', () => {
    it('prefers the live session user id over useSupabaseUser when both are present', async () => {
      getSessionMock.mockResolvedValue({ data: { session: { user: { id: 'session-uid' } } } })
      userRef.value!.id = 'reactive-uid'
      callMock.mockResolvedValueOnce({ display_name: 'Alice', avatar_url: null })
      wrapper = await mountSuspended(ProfilePage)

      await (wrapper.vm as VmAny).onProfileSave()

      expect(callMock).toHaveBeenCalledWith('/user/session-uid/profile', expect.objectContaining({ method: 'PUT' }))
    })

    it('falls back to useSupabaseUser().value.id when the session has no user', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value!.id = 'reactive-uid'
      callMock.mockResolvedValueOnce({ display_name: 'Alice', avatar_url: null })
      wrapper = await mountSuspended(ProfilePage)

      await (wrapper.vm as VmAny).onProfileSave()

      expect(callMock).toHaveBeenCalledWith('/user/reactive-uid/profile', expect.objectContaining({ method: 'PUT' }))
    })

    it('does nothing when neither the session nor the reactive user has an id', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value = null
      wrapper = await mountSuspended(ProfilePage)

      await (wrapper.vm as VmAny).onProfileSave()

      expect(callMock).not.toHaveBeenCalled()
    })
  })

  describe('onAvatarChange', () => {
    it('rejects a file over 2MB with an error toast and does not set a preview/file', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      const bigFile = makeFile('big.png', 2 * 1024 * 1024 + 1)

      vm.onAvatarChange(fileChangeEvent(bigFile))
      await flushPromises()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Image too large',
        description: 'Please choose an image under 2MB.',
        color: 'error'
      })
      expect(vm.avatarFile).toBeNull()
      expect(vm.avatarPreview).toBe('')
    })

    it('accepts a file at/under 2MB: sets avatarFile and a preview URL without a toast', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      const okFile = makeFile('ok.png', 2 * 1024 * 1024)

      vm.onAvatarChange(fileChangeEvent(okFile))
      await flushPromises()

      // Vue wraps the File in a reactive proxy, so it's no longer `===` the
      // original object even though it holds the same data - compare identity
      // via name/type instead.
      expect(vm.avatarFile).toBeInstanceOf(File)
      expect((vm.avatarFile as File).name).toBe('ok.png')
      expect(vm.avatarPreview).toBe('blob:mock-url')
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('is a no-op when no file is selected', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      vm.onAvatarChange(fileChangeEvent(undefined))
      await flushPromises()

      expect(vm.avatarFile).toBeNull()
      expect(vm.avatarPreview).toBe('')
      expect(toastAddMock).not.toHaveBeenCalled()
    })
  })

  describe('General Settings card: template interactions', () => {
    it('clicking "Change photo" triggers a click on the hidden file input', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const inputEl = wrapper.find('input[type="file"]').element as HTMLInputElement
      const clickSpy = vi.spyOn(inputEl, 'click').mockImplementation(() => {})
      const changePhotoBtn = wrapper.findAll('button').find(b => b.text() === 'Change photo')
      expect(changePhotoBtn).toBeTruthy()

      await changePhotoBtn!.trigger('click')

      expect(clickSpy).toHaveBeenCalledTimes(1)
    })

    it('typing into the Display Name input updates displayName via v-model', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      const input = wrapper.find('input[placeholder="Enter your display name"]')
      expect(input.exists()).toBe(true)
      await input.setValue('New Display Name')

      expect(vm.displayName).toBe('New Display Name')
    })
  })

  describe('onProfileSave', () => {
    it('PUTs a FormData body to /user/:id/profile with the display name (and avatar, if selected)', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      vm.displayName = 'New Name'
      const okFile = makeFile('ok.png', 1024)
      vm.onAvatarChange(fileChangeEvent(okFile))

      callMock.mockResolvedValueOnce({ display_name: 'New Name', avatar_url: 'https://cdn.example.com/new.png' })
      await vm.onProfileSave()

      expect(callMock).toHaveBeenCalledTimes(1)
      const [path, opts] = callMock.mock.calls[0]!
      expect(path).toBe('/user/session-uid/profile')
      expect(opts.method).toBe('PUT')
      expect(opts.body).toBeInstanceOf(FormData)
      const form = opts.body as FormData
      expect(form.get('display_name')).toBe('New Name')
      const uploaded = form.get('avatar') as File
      expect(uploaded).toBeInstanceOf(File)
      expect(uploaded.name).toBe('ok.png')
    })

    it('omits the avatar field entirely when no new file was chosen', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      callMock.mockResolvedValueOnce({ display_name: 'Alice', avatar_url: null })
      await vm.onProfileSave()

      const form = callMock.mock.calls[0]![1].body as FormData
      expect(form.has('avatar')).toBe(false)
    })

    it('on success: refreshes the session, updates avatarUrl, clears the pending file/preview, and toasts success', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      vm.onAvatarChange(fileChangeEvent(makeFile('ok.png', 1024)))

      callMock.mockResolvedValueOnce({ display_name: 'Alice', avatar_url: 'https://cdn.example.com/new.png' })
      await vm.onProfileSave()

      expect(refreshSessionMock).toHaveBeenCalledTimes(1)
      expect(vm.avatarUrl).toBe('https://cdn.example.com/new.png')
      expect(vm.avatarFile).toBeNull()
      expect(vm.avatarPreview).toBe('')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Profile updated',
        description: 'Your profile settings have been saved.',
        color: 'success'
      })
    })

    it('keeps the previous avatarUrl when the response has no avatar_url', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      const priorUrl = vm.avatarUrl

      callMock.mockResolvedValueOnce({ display_name: 'Alice', avatar_url: null })
      await vm.onProfileSave()

      expect(vm.avatarUrl).toBe(priorUrl)
    })

    it('toggles profileLoading around the request', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      let resolveCall!: (v: unknown) => void
      callMock.mockReturnValueOnce(new Promise((resolve) => {
        resolveCall = resolve
      }))

      const pending = vm.onProfileSave()
      await flushPromises()
      expect(vm.profileLoading).toBe(true)

      resolveCall({ display_name: 'Alice', avatar_url: null })
      await pending

      expect(vm.profileLoading).toBe(false)
    })

    it('shows an error toast with the API detail when the request fails', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      callMock.mockRejectedValueOnce({ data: { detail: 'Name contains invalid characters' } })
      await vm.onProfileSave()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to update profile',
        description: 'Name contains invalid characters',
        color: 'error'
      })
      expect(vm.profileLoading).toBe(false)
    })

    it('falls back to err.message when the failure has no API detail', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      callMock.mockRejectedValueOnce(new Error('network exploded'))
      await vm.onProfileSave()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to update profile',
        description: 'network exploded',
        color: 'error'
      })
    })
  })

  describe('Email Address form: real DOM submission', () => {
    it('submits a valid new email through the form, calling the API and showing a success toast', async () => {
      wrapper = await mountSuspended(ProfilePage)
      callMock.mockResolvedValueOnce({})

      await fillAndSubmitEmail(wrapper, 'new@example.com')

      expect(callMock).toHaveBeenCalledWith('/user/session-uid/email', {
        method: 'PUT',
        body: { new_email: 'new@example.com' }
      })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Email change requested',
        description: 'Please check your inbox for verification links.',
        color: 'success'
      })
    })

    it('does not submit an invalid email (fails Zod validation, no API call)', async () => {
      wrapper = await mountSuspended(ProfilePage)

      await fillAndSubmitEmail(wrapper, 'not-an-email')

      expect(callMock).not.toHaveBeenCalled()
    })
  })

  describe('onEmailSubmit (handler logic, invoked directly with a submit payload)', () => {
    it('PUTs /user/:id/email with new_email and shows a success toast', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      callMock.mockResolvedValueOnce({})

      await vm.onEmailSubmit({ data: { email: 'new@example.com' } })

      expect(callMock).toHaveBeenCalledWith('/user/session-uid/email', {
        method: 'PUT',
        body: { new_email: 'new@example.com' }
      })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Email change requested',
        description: 'Please check your inbox for verification links.',
        color: 'success'
      })
      expect(vm.emailLoading).toBe(false)
    })

    it('toggles emailLoading around the request', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      let resolveCall!: (v: unknown) => void
      callMock.mockReturnValueOnce(new Promise((resolve) => {
        resolveCall = resolve
      }))

      const pending = vm.onEmailSubmit({ data: { email: 'new@example.com' } })
      await flushPromises()
      expect(vm.emailLoading).toBe(true)

      resolveCall({})
      await pending

      expect(vm.emailLoading).toBe(false)
    })

    it('shows an error toast with err.message on failure', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      callMock.mockRejectedValueOnce(new Error('email already in use'))

      await vm.onEmailSubmit({ data: { email: 'new@example.com' } })

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to update email',
        description: 'email already in use',
        color: 'error'
      })
      expect(vm.emailLoading).toBe(false)
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      callMock.mockRejectedValueOnce('boom')

      await vm.onEmailSubmit({ data: { email: 'new@example.com' } })

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to update email',
        description: 'Something went wrong',
        color: 'error'
      })
    })

    it('does not submit when getUserId resolves to null', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value = null
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      await vm.onEmailSubmit({ data: { email: 'new@example.com' } })

      expect(callMock).not.toHaveBeenCalled()
    })
  })

  describe('Security Settings form: real DOM submission', () => {
    it('submits matching valid passwords through the form, calling the API and showing a success toast', async () => {
      wrapper = await mountSuspended(ProfilePage)
      callMock.mockResolvedValueOnce({})

      await fillAndSubmitPassword(wrapper, 'oldpassword1', 'newpassword1', 'newpassword1')

      expect(callMock).toHaveBeenCalledWith('/user/session-uid/password', {
        method: 'PUT',
        body: { current_password: 'oldpassword1', new_password: 'newpassword1' }
      })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Password updated',
        description: 'Your password was changed successfully.',
        color: 'success'
      })
    })

    it('does not submit when confirmPassword does not match (fails .refine(), no API call)', async () => {
      wrapper = await mountSuspended(ProfilePage)

      await fillAndSubmitPassword(wrapper, 'oldpassword1', 'newpassword1', 'mismatch12345')

      expect(callMock).not.toHaveBeenCalled()
    })
  })

  describe('passwordSchema (.refine() cross-field validation)', () => {
    // vm.passwordSchema is a plain top-level `<script setup>` const (same as
    // vm.onPasswordSubmit etc. above) - accessible on wrapper.vm without
    // defineExpose, per this file's established convention.
    it('rejects when newPassword and confirmPassword do not match, attaching the error to confirmPassword', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      const result = vm.passwordSchema.safeParse({
        currentPassword: 'oldpassword1',
        newPassword: 'newpassword1',
        confirmPassword: 'somethingElse1'
      })

      expect(result.success).toBe(false)
      expect(result.error.issues[0]).toMatchObject({
        path: ['confirmPassword'],
        message: 'Passwords don\'t match'
      })
    })

    it('accepts when newPassword and confirmPassword match and all fields meet the length minimum', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      const result = vm.passwordSchema.safeParse({
        currentPassword: 'oldpassword1',
        newPassword: 'newpassword1',
        confirmPassword: 'newpassword1'
      })

      expect(result.success).toBe(true)
    })
  })

  describe('onPasswordSubmit (handler logic, invoked directly with a submit payload)', () => {
    it('PUTs /user/:id/password with current/new passwords and shows a success toast', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      callMock.mockResolvedValueOnce({})

      await vm.onPasswordSubmit({
        data: { currentPassword: 'oldpassword1', newPassword: 'newpassword1', confirmPassword: 'newpassword1' }
      })

      expect(callMock).toHaveBeenCalledWith('/user/session-uid/password', {
        method: 'PUT',
        body: { current_password: 'oldpassword1', new_password: 'newpassword1' }
      })
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Password updated',
        description: 'Your password was changed successfully.',
        color: 'success'
      })
      expect(vm.passwordLoading).toBe(false)
    })

    it('toggles passwordLoading around the request', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      let resolveCall!: (v: unknown) => void
      callMock.mockReturnValueOnce(new Promise((resolve) => {
        resolveCall = resolve
      }))

      const pending = vm.onPasswordSubmit({
        data: { currentPassword: 'oldpassword1', newPassword: 'newpassword1', confirmPassword: 'newpassword1' }
      })
      await flushPromises()
      expect(vm.passwordLoading).toBe(true)

      resolveCall({})
      await pending

      expect(vm.passwordLoading).toBe(false)
    })

    it('shows an error toast with err.message on failure', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      callMock.mockRejectedValueOnce(new Error('incorrect current password'))

      await vm.onPasswordSubmit({
        data: { currentPassword: 'oldpassword1', newPassword: 'newpassword1', confirmPassword: 'newpassword1' }
      })

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to update password',
        description: 'incorrect current password',
        color: 'error'
      })
      expect(vm.passwordLoading).toBe(false)
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      callMock.mockRejectedValueOnce('boom')

      await vm.onPasswordSubmit({
        data: { currentPassword: 'oldpassword1', newPassword: 'newpassword1', confirmPassword: 'newpassword1' }
      })

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to update password',
        description: 'Something went wrong',
        color: 'error'
      })
    })

    it('does not submit when getUserId resolves to null', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value = null
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny

      await vm.onPasswordSubmit({
        data: { currentPassword: 'oldpassword1', newPassword: 'newpassword1', confirmPassword: 'newpassword1' }
      })

      expect(callMock).not.toHaveBeenCalled()
    })
  })

  describe('Danger Zone: delete account modal gating + handleDeleteAccount', () => {
    it('the confirmation modal starts closed', async () => {
      wrapper = await mountSuspended(ProfilePage)
      expect((wrapper.vm as VmAny).deleteModalOpen).toBe(false)
    })

    it('clicking "Delete Account" in the Danger Zone opens the confirmation modal', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const trigger = wrapper.findAll('button').find(b => b.text() === 'Delete Account')
      expect(trigger).toBeTruthy()

      await trigger!.trigger('click')

      expect((wrapper.vm as VmAny).deleteModalOpen).toBe(true)
    })

    it('the modal syncs deleteModalOpen back to false when the UModal component emits update:open (v-model write side)', async () => {
      // <UModal v-model:open="deleteModalOpen"> compiles to a bound `:open`
      // prop plus an `@update:open` listener that writes back to
      // `deleteModalOpen`. The UModal component itself (unlike its
      // `#content` slot - see note below) renders inline, not behind a
      // <Teleport>, so it's directly findable and we can emit the event a
      // real close interaction (Escape, overlay click, etc.) would trigger.
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      vm.deleteModalOpen = true
      await wrapper.vm.$nextTick()

      const modal = wrapper.findComponent({ name: 'UModal' })
      expect(modal.exists()).toBe(true)

      modal.vm.$emit('update:open', false)
      await wrapper.vm.$nextTick()

      expect(vm.deleteModalOpen).toBe(false)
    })

    // The modal's "Cancel" and "Delete Account" (confirm) buttons live inside
    // <UModal>'s #content slot, which Nuxt UI/Reka UI portals via <Teleport
    // to="body">. Verified empirically (dumping document.body.innerHTML after
    // opening the modal on an un-stubbed mount) that the teleported content
    // never lands anywhere - it stays just `<div id="__nuxt">` - because this
    // bare mountSuspended(ProfilePage) page has no <UApp> ancestor to provide
    // the portal-target injection Nuxt UI's usePortal() composable expects.
    // To reach the real Cancel button's own `@click="deleteModalOpen = false"`
    // handler (as opposed to testing handleDeleteAccount/deleteModalOpen at
    // the state level, like the other tests in this describe block do), stub
    // UModal with a minimal component that renders its `#content` slot
    // inline instead of teleporting it - this is test-only wiring, not a
    // change to app source, and every other button in it is the real UButton.
    it('clicking "Cancel" inside the confirmation modal closes it without calling the delete API', async () => {
      wrapper = await mountSuspended(ProfilePage, {
        global: {
          stubs: {
            UModal: { template: '<div><slot name="content" /></div>' }
          }
        }
      })
      const vm = wrapper.vm as VmAny
      vm.deleteModalOpen = true
      await wrapper.vm.$nextTick()

      const cancelBtn = wrapper.findAll('button').find(b => b.text() === 'Cancel')
      expect(cancelBtn).toBeTruthy()

      await cancelBtn!.trigger('click')

      expect(vm.deleteModalOpen).toBe(false)
      expect(callMock).not.toHaveBeenCalled()
    })

    // Note: the modal's "Cancel" and "Delete Account" (confirm) buttons live
    // inside <UModal>'s #content slot, which Nuxt UI/Reka UI portals via
    // <Teleport> once `deleteModalOpen` flips true. mountSuspended() here
    // mounts the bare page (no <UApp> root, which is what normally supplies
    // the teleport target/providers in the real app), so that portalled
    // content never lands anywhere queryable via `wrapper` or
    // `document.body` in this harness - confirmed by dumping
    // `document.body.innerHTML` after opening the modal, which stays just
    // `<div id="__nuxt">`. We instead exercise deleteModalOpen/handleDeleteAccount
    // at the state/method level, which is what's actually under test here.
    it('handleDeleteAccount is a no-op (no DELETE, no signOut, no redirect) when getUserId resolves to null', async () => {
      getSessionMock.mockResolvedValue({ data: { session: null } })
      userRef.value = null
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      vm.deleteModalOpen = true

      await vm.handleDeleteAccount()

      expect(callMock).not.toHaveBeenCalled()
      expect(signOutMock).not.toHaveBeenCalled()
      // Early-return path never reaches the finally block that would reset it.
      expect(vm.deleteModalOpen).toBe(true)
    })

    it('once the modal is open: DELETEs the account, signs out, toasts success, redirects home, and closes the modal', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      const pushSpy = spyOnRouterPush(wrapper)
      vm.deleteModalOpen = true
      await wrapper.vm.$nextTick()

      callMock.mockResolvedValueOnce({})
      await vm.handleDeleteAccount()

      expect(callMock).toHaveBeenCalledWith('/user/session-uid', { method: 'DELETE' })
      expect(signOutMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Account deleted',
        description: 'Your account and data have been permanently removed.',
        color: 'success'
      })
      expect(pushSpy).toHaveBeenCalledWith('/')
      expect(vm.deleteModalOpen).toBe(false)
      expect(vm.deleteLoading).toBe(false)
    })

    it('toggles deleteLoading around the request', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      vm.deleteModalOpen = true

      let resolveCall!: (v: unknown) => void
      callMock.mockReturnValueOnce(new Promise((resolve) => {
        resolveCall = resolve
      }))

      const pending = vm.handleDeleteAccount()
      await flushPromises()
      expect(vm.deleteLoading).toBe(true)

      resolveCall({})
      await pending

      expect(vm.deleteLoading).toBe(false)
    })

    it('on failure: shows an error toast, does not sign out or redirect, but still closes the modal', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      const pushSpy = spyOnRouterPush(wrapper)
      vm.deleteModalOpen = true

      callMock.mockRejectedValueOnce(new Error('cannot delete: active orders'))
      await vm.handleDeleteAccount()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to delete account',
        description: 'cannot delete: active orders',
        color: 'error'
      })
      expect(signOutMock).not.toHaveBeenCalled()
      expect(pushSpy).not.toHaveBeenCalled()
      // finally always resets both, even on failure
      expect(vm.deleteModalOpen).toBe(false)
      expect(vm.deleteLoading).toBe(false)
    })

    it('falls back to a generic message when the thrown error is not an Error instance', async () => {
      wrapper = await mountSuspended(ProfilePage)
      const vm = wrapper.vm as VmAny
      vm.deleteModalOpen = true

      callMock.mockRejectedValueOnce('boom')
      await vm.handleDeleteAccount()

      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Failed to delete account',
        description: 'Something went wrong',
        color: 'error'
      })
    })
  })
})
