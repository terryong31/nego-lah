import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { useApi } from '../../app/composables/useApi'

const { getSessionMock, signOutMock } = vi.hoisted(() => ({
  getSessionMock: vi.fn(),
  signOutMock: vi.fn()
}))

const { toastAddMock } = vi.hoisted(() => ({
  toastAddMock: vi.fn()
}))

const { navigateToMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn()
}))

const { fetchMock } = vi.hoisted(() => ({
  fetchMock: vi.fn().mockResolvedValue({ ok: true })
}))

mockNuxtImport('useSupabaseClient', () => {
  return () => ({
    auth: {
      getSession: getSessionMock,
      signOut: signOutMock
    }
  })
})

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

// $fetch is exposed as a genuine global (by ofetch/Nitro), not routed through
// Nuxt's unimport registry, so `mockNuxtImport('$fetch', ...)` fails with
// "Cannot find import "$fetch" to mock" — stub the global directly instead.
describe('composables/useApi', () => {
  beforeEach(() => {
    getSessionMock.mockReset().mockResolvedValue({ data: { session: null } })
    signOutMock.mockReset().mockResolvedValue({ error: null })
    toastAddMock.mockReset()
    navigateToMock.mockReset()
    fetchMock.mockReset().mockResolvedValue({ ok: true })
    vi.stubGlobal('$fetch', fetchMock)
    routeStub.fullPath = '/'
  })

  it('calls $fetch with the configured API base URL and path', async () => {
    const { call } = useApi()
    await call('/orders')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('http://localhost:8000/orders')
  })

  it('adds an Authorization header when a session exists', async () => {
    getSessionMock.mockResolvedValue({ data: { session: { access_token: 'token-123' } } })

    const { call } = useApi()
    await call('/orders')

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers).toMatchObject({ Authorization: 'Bearer token-123' })
  })

  it('omits the Authorization header when there is no session', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } })

    const { call } = useApi()
    await call('/orders')

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers).not.toHaveProperty('Authorization')
  })

  it('lets caller-supplied headers override the session Authorization header (spread order)', async () => {
    getSessionMock.mockResolvedValue({ data: { session: { access_token: 'token-123' } } })

    const { call } = useApi()
    await call('/orders', { headers: { 'Authorization': 'Custom scheme', 'X-Test': '1' } })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers).toMatchObject({ 'Authorization': 'Custom scheme', 'X-Test': '1' })
  })

  it('preserves other caller-supplied opts alongside the computed headers', async () => {
    const { call } = useApi()
    await call('/orders', { method: 'POST', body: { foo: 'bar' } })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.method).toBe('POST')
    expect(options.body).toEqual({ foo: 'bar' })
  })

  describe('onResponseError', () => {
    async function getErrorHandler() {
      const { call } = useApi()
      await call('/orders')
      const [, options] = fetchMock.mock.calls[0]
      expect(options.onResponseError).toBeTypeOf('function')
      return options.onResponseError as (ctx: { response: { status: number, _data?: unknown } }) => Promise<void>
    }

    it('signs out and redirects to /login on a 401', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 401, _data: {} } })

      expect(signOutMock).toHaveBeenCalledTimes(1)
      expect(navigateToMock).toHaveBeenCalledWith({ path: '/login' })
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('signs out and redirects to /login on a 403 with a "banned" detail message', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: 'You have been BANNED for spamming' } } })

      expect(signOutMock).toHaveBeenCalledTimes(1)
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
      expect(signOutMock).toHaveBeenCalledTimes(1)
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

      expect(signOutMock).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('does not sign out or redirect on a 403 with a non-string detail', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403, _data: { detail: { code: 'banned' } } } })

      expect(signOutMock).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('does not sign out or redirect on a 403 with no _data at all', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 403 } })

      expect(signOutMock).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })

    it('ignores unrelated error statuses (e.g. 500)', async () => {
      const onResponseError = await getErrorHandler()

      await onResponseError({ response: { status: 500, _data: { detail: 'server error' } } })

      expect(signOutMock).not.toHaveBeenCalled()
      expect(navigateToMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })
  })
})
