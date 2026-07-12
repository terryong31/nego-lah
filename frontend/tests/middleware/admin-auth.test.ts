import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import type { RouteLocationNormalized } from 'vue-router'
import adminAuthMiddleware from '~/middleware/admin-auth'

// `useAdminApi` and `navigateTo` are both Nuxt auto-imports, so they need to be
// swapped out via `mockNuxtImport` (module-level, hoisted) rather than a plain
// `vi.mock`. `useAdminApi` itself already has full unit coverage in
// tests/composables/useAdminApi.test.ts, so here we only care that the
// middleware calls `call('/auth/session')` and reacts correctly to
// resolution/rejection.
const { callMock, navigateToMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  navigateToMock: vi.fn((path: string) => ({ __redirect: path }))
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('navigateTo', () => navigateToMock)

function makeRoute(path = '/_console'): RouteLocationNormalized {
  return { path } as RouteLocationNormalized
}

// Plain `vi.fn()` mocks (as opposed to `vi.spyOn` spies) are NOT cleared by the
// global `vi.restoreAllMocks()` in tests/setup.ts's afterEach, so call history
// would otherwise leak across `it` blocks in this file. Reset explicitly.
beforeEach(() => {
  callMock.mockReset()
  navigateToMock.mockClear()
})

describe('middleware/admin-auth', () => {
  it('checks the admin session and allows navigation through (returns nothing) when it succeeds', async () => {
    callMock.mockResolvedValueOnce({ ok: true })

    const result = await adminAuthMiddleware(makeRoute(), makeRoute('/_console/login'))

    expect(callMock).toHaveBeenCalledExactlyOnceWith('/auth/session')
    expect(navigateToMock).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })

  it('redirects to /_console/login when the session check rejects (e.g. missing/expired admin cookie)', async () => {
    callMock.mockRejectedValueOnce(Object.assign(new Error('Unauthorized'), { statusCode: 401 }))

    const result = await adminAuthMiddleware(makeRoute(), makeRoute('/'))

    expect(callMock).toHaveBeenCalledExactlyOnceWith('/auth/session')
    expect(navigateToMock).toHaveBeenCalledExactlyOnceWith('/_console/login')
    expect(result).toEqual({ __redirect: '/_console/login' })
  })

  it('redirects regardless of the rejection reason (any error is treated as "not authenticated")', async () => {
    callMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    const result = await adminAuthMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).toHaveBeenCalledExactlyOnceWith('/_console/login')
    expect(result).toEqual({ __redirect: '/_console/login' })
  })
})
