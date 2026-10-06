import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { useApi } from '../../app/composables/useApi'
import { makeAuthStub } from '../helpers/auth'

const userRef = ref<{ id: string } | null>({ id: 'u1' })
const authStub = makeAuthStub(userRef)

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

const { navigateToMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn()
}))

const { fetchMock } = vi.hoisted(() => ({
  fetchMock: vi.fn().mockResolvedValue({ ok: true })
}))

mockNuxtImport('useAuth', () => () => authStub)

mockNuxtImport('useToast', () => {
  return () => ({
    add: toastAddMock
  })
})

mockNuxtImport('navigateTo', () => navigateToMock)

// The 401 bounce carries the page the caller was on, so the route the
// composable reads has to be controllable per-test. `fullPath` is reset to '/'
// in beforeEach — the "nothing worth returning to" case.
const routeStub = reactive<{ fullPath: string }>({ fullPath: '/' })
mockNuxtImport('useRoute', () => () => routeStub)

// Nuxt 4.5 made `$fetch` an auto-import (from `#build/fetch.mjs`), so it is
// mocked like any other import; stubbing the global no longer reaches it.
mockNuxtImport('$fetch', () => fetchMock)

describe('composables/useApi', () => {
  beforeEach(() => {
    authStub.clearSession.mockClear()
    userRef.value = { id: 'u1' }
    document.cookie = 'nl_csrf=csrf-abc'
    toastAddMock.mockReset()
    navigateToMock.mockReset()
    fetchMock.mockReset().mockResolvedValue({ ok: true })
    routeStub.fullPath = '/'
  })

  it('calls $fetch with the configured API base URL and path', async () => {
    const { call } = useApi()
    await call('/orders')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('http://localhost:8000/orders')
  })

  // SPEC-093: the session is an httpOnly cookie on the API host, and this app is
  // a different origin from it. Without `credentials: 'include'` the browser
  // sends no cookie at all and every call 401s.
  it('sends the session cookie cross-origin', async () => {
    const { call } = useApi()
    await call('/orders')

    const [, options] = fetchMock.mock.calls[0]
    expect(options.credentials).toBe('include')
  })

  it('never sends an Authorization header, because there is no token to send', async () => {
    const { call } = useApi()
    await call('/orders')

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers).not.toHaveProperty('Authorization')
  })

  // The cookie is auto-sent, which is exactly what a bearer header was not — so
  // a mutating call has to prove it came from this app, not from another origin.
  it('echoes the CSRF cookie back as a header', async () => {
    const { call } = useApi()
    await call('/chat/read', { method: 'POST' })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-abc' })
  })

  it('lets caller-supplied headers win over the computed ones (spread order)', async () => {
    const { call } = useApi()
    await call('/orders', { headers: { 'X-CSRF-Token': 'explicit', 'X-Test': '1' } })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers).toMatchObject({ 'X-CSRF-Token': 'explicit', 'X-Test': '1' })
  })

  it('preserves other caller-supplied opts alongside the computed headers', async () => {
    const { call } = useApi()
    await call('/orders', { method: 'POST', body: { foo: 'bar' } })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.method).toBe('POST')
    expect(options.body).toEqual({ foo: 'bar' })
  })

  it('does not forward the reauth flag to $fetch', async () => {
    const { call } = useApi()
    await call('/user/u1/email', { method: 'PUT', reauth: true, body: { a: 1 } })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.method).toBe('PUT')
    expect(options).not.toHaveProperty('reauth')
  })

  describe('onResponseError', () => {
    async function getErrorHandler(opts?: Record<string, unknown>) {
      const { call } = useApi()
      await call('/orders', opts)
      const [, options] = fetchMock.mock.calls[0]
      expect(options.onResponseError).toBeTypeOf('function')
      return options.onResponseError as (ctx: { response: { status: number, _data?: unknown } }) => Promise<void>
    }

    // SPEC-056 #3/#7. Re-authentication endpoints answer 401 for "that password
    // is wrong", which says nothing about the session cookie that carried the
    // request. Signing the user out on it would mean mistyping your password on
    // the profile page logs you out of a session that was never in doubt.
    it('keeps the session when a re-auth call reports a wrong password', async () => {
      const onResponseError = await getErrorHandler({ reauth: true })

      await onResponseError({ response: { status: 401, _data: { detail: 'Current password is incorrect' } } })

      expect(authStub.clearSession).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
    })

    it('still signs out a banned account even on a re-auth call', async () => {
      const onResponseError = await getErrorHandler({ reauth: true })

      await onResponseError({ response: { status: 403, _data: { detail: 'Account banned' } } })

      expect(authStub.clearSession).toHaveBeenCalledTimes(1)
    })

    it('signs out and redirects to /login on a 401', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 401, _data: {} } })

      expect(authStub.clearSession).toHaveBeenCalledTimes(1)
      expect(navigateToMock).toHaveBeenCalledWith({ path: '/login' })
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('signs out and redirects to /login on a 403 with a "banned" detail message', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: 'You have been BANNED for spamming' } } })

      expect(authStub.clearSession).toHaveBeenCalledTimes(1)
      expect(navigateToMock).toHaveBeenCalledWith({ path: '/login' })
    })

    it('shows a distinct "Account suspended" toast for the banned 403 case', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: 'banned' } } })

      expect(toastAddMock).toHaveBeenCalledTimes(1)
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Account suspended',
        description: 'Your account has been banned.',
        color: 'error'
      })
    })

    it('does not show the banned toast for a plain 401', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 401, _data: { detail: 'expired token' } } })

      expect(toastAddMock).not.toHaveBeenCalled()
      expect(authStub.clearSession).toHaveBeenCalledTimes(1)
      expect(navigateToMock).toHaveBeenCalledWith({ path: '/login' })
    })

    it('detects the "banned" keyword case-insensitively', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: 'Banned' } } })

      expect(toastAddMock).toHaveBeenCalledTimes(1)
    })

    it('carries the page the caller was on through the 401 bounce, so login can send them back', async () => {
      routeStub.fullPath = '/chat?item_id=item-1'
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 401, _data: {} } })

      expect(navigateToMock).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/chat?item_id=item-1' }
      })
    })

    it('carries the current page through the banned 403 bounce too', async () => {
      routeStub.fullPath = '/orders'
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: 'banned' } } })

      expect(navigateToMock).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/orders' }
      })
    })

    it('reads the route at the moment the request fails, not when useApi() was created', async () => {
      routeStub.fullPath = '/orders'
      const onResponseError = await getErrorHandler()
      routeStub.fullPath = '/profile'

      await onResponseError({ response: { status: 401, _data: {} } })

      expect(navigateToMock).toHaveBeenCalledWith({
        path: '/login',
        query: { redirect: '/profile' }
      })
    })

    it('does not sign out or redirect on a 403 that is not a banned message', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: 'forbidden: insufficient permissions' } } })

      expect(authStub.clearSession).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('does not sign out or redirect on a 403 with a non-string detail', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: { code: 'banned' } } } })

      expect(authStub.clearSession).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('does not sign out or redirect on a 403 with no _data at all', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403 } })

      expect(authStub.clearSession).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('ignores unrelated error statuses (e.g. 500)', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 500, _data: { detail: 'server error' } } })

      expect(authStub.clearSession).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })
  })
})
