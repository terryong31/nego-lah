import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { useAdminApi } from '../../app/composables/useAdminApi'

// Nuxt 4.5 made `$fetch` an auto-import (from `#build/fetch.mjs`), so it is
// mocked like any other import; stubbing the global no longer reaches it.
const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))
mockNuxtImport('$fetch', () => fetchMock)

// Reset BEFORE each test: the mock is installed at import time, so the app's
// own boot requests (the session probe) land in it before the first test runs.
beforeEach(() => {
  fetchMock.mockReset()
})

// In the test environment there is no document.cookie, so getCsrfToken() returns ''.
// Every call now includes headers: { 'X-CSRF-Token': '' } at minimum.
const CSRF_HEADERS = { 'X-CSRF-Token': '' }

describe('composables/useAdminApi', () => {
  it('calls $fetch against `${apiBaseUrl}/admin${path}` with credentials: include and CSRF header', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true })
    const { call } = useAdminApi()

    const result = await call('/users')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/admin/users', {
      credentials: 'include',
      headers: CSRF_HEADERS
    })
    expect(result).toEqual({ ok: true })
  })

  it('builds the URL by concatenating base and path exactly (no extra slash normalization)', async () => {
    fetchMock.mockResolvedValueOnce({})
    const { call } = useAdminApi()

    await call('/orders/123')

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/admin/orders/123', expect.anything())
  })

  it('spreads caller-supplied opts into the request after credentials, merging headers', async () => {
    fetchMock.mockResolvedValueOnce({ id: 1 })
    const { call } = useAdminApi()

    await call('/orders/1', { method: 'PATCH', body: { status: 'fulfilled' } })

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/admin/orders/1', {
      credentials: 'include',
      method: 'PATCH',
      body: { status: 'fulfilled' },
      headers: CSRF_HEADERS
    })
  })

  it('lets caller-supplied opts override the default credentials value, since opts are spread after it', async () => {
    fetchMock.mockResolvedValueOnce({})
    const { call } = useAdminApi()

    await call('/users', { credentials: 'omit' })

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/admin/users', {
      credentials: 'omit',
      headers: CSRF_HEADERS
    })
  })

  it('includes credentials and the CSRF header when no opts are provided', async () => {
    fetchMock.mockResolvedValueOnce({})
    const { call } = useAdminApi()

    await call('/dashboard')

    const [, options] = fetchMock.mock.calls[0]
    expect(options).toEqual({ credentials: 'include', headers: CSRF_HEADERS })
  })

  it('propagates rejections from $fetch (e.g. a 401/403 from an expired admin session)', async () => {
    const error = Object.assign(new Error('Unauthorized'), { statusCode: 401 })
    fetchMock.mockRejectedValueOnce(error)
    const { call } = useAdminApi()

    await expect(call('/users')).rejects.toThrow('Unauthorized')
  })

  it('passes the generic type through purely for TypeScript inference — returns whatever $fetch resolves at runtime', async () => {
    const payload = [{ id: 1, name: 'Alice' }, { id: 2, name: 'Bob' }]
    fetchMock.mockResolvedValueOnce(payload)
    const { call } = useAdminApi()

    const result = await call<typeof payload>('/users')

    expect(result).toBe(payload)
  })

  it('recomputes the target URL per call using the same base for multiple sequential calls', async () => {
    fetchMock.mockResolvedValueOnce({ a: 1 }).mockResolvedValueOnce({ b: 2 })
    const { call } = useAdminApi()

    await call('/a')
    await call('/b')

    expect(fetchMock).toHaveBeenNthCalledWith(1, 'http://localhost:8000/admin/a', { credentials: 'include', headers: CSRF_HEADERS })
    expect(fetchMock).toHaveBeenNthCalledWith(2, 'http://localhost:8000/admin/b', { credentials: 'include', headers: CSRF_HEADERS })
  })
})
