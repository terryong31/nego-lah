import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'

const { navigateToMock } = vi.hoisted(() => ({ navigateToMock: vi.fn() }))

mockNuxtImport('navigateTo', () => navigateToMock)

beforeEach(() => {
  navigateToMock.mockClear()
})

function makeRoute(path: string, query: Record<string, string | undefined> = {}, hash: string = '') {
  return { path, query, hash } as unknown as RouteLocationNormalized
}

describe('middleware/auth-redirect.global.ts', () => {
  it('does nothing when there is no auth query or hash param', async () => {
    const middleware = (await import('~/middleware/auth-redirect.global')).default

    const result = middleware(makeRoute('/'), makeRoute('/'))

    expect(result).toBeUndefined()
    expect(navigateToMock).not.toHaveBeenCalled()
  })

  it('redirects to /confirm when code is present on the root route', async () => {
    const middleware = (await import('~/middleware/auth-redirect.global')).default

    middleware(
      makeRoute('/', { code: 'test-code-123' }),
      makeRoute('/')
    )

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/confirm',
      query: {
        code: 'test-code-123'
      }
    })
  })

  it('redirects to /confirm when token_hash is present on another route', async () => {
    const middleware = (await import('~/middleware/auth-redirect.global')).default

    middleware(
      makeRoute('/items', { token_hash: 'hash-abc', type: 'signup' }),
      makeRoute('/')
    )

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/confirm',
      query: {
        token_hash: 'hash-abc',
        type: 'signup'
      }
    })
  })

  it('redirects to /confirm when error and error_code are in query', async () => {
    const middleware = (await import('~/middleware/auth-redirect.global')).default

    middleware(
      makeRoute('/', {
        error: 'access_denied',
        error_code: 'otp_expired',
        error_description: 'Email link is invalid or has expired'
      }),
      makeRoute('/')
    )

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/confirm',
      query: {
        error: 'access_denied',
        error_code: 'otp_expired',
        error_description: 'Email link is invalid or has expired'
      }
    })
  })

  it('redirects to /confirm when error is in hash', async () => {
    const middleware = (await import('~/middleware/auth-redirect.global')).default

    middleware(
      makeRoute('/', {}, '#error=access_denied&error_code=otp_expired'),
      makeRoute('/')
    )

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/confirm',
      query: {},
      hash: '#error=access_denied&error_code=otp_expired'
    })
  })

  it('does not redirect if already on /confirm', async () => {
    const middleware = (await import('~/middleware/auth-redirect.global')).default

    const result = middleware(
      makeRoute('/confirm', { code: 'test-code-123' }),
      makeRoute('/')
    )

    expect(result).toBeUndefined()
    expect(navigateToMock).not.toHaveBeenCalled()
  })
})
