import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'

const { navigateToMock } = vi.hoisted(() => ({ navigateToMock: vi.fn() }))

mockNuxtImport('navigateTo', () => navigateToMock)

beforeEach(() => {
  navigateToMock.mockClear()
})

function makeRoute(path: string, query: Record<string, string | undefined> = {}, hash: string = '') {
  const qs = new URLSearchParams(
    Object.entries(query).filter((e): e is [string, string] => typeof e[1] === 'string')
  ).toString()
  const fullPath = `${path}${qs ? `?${qs}` : ''}${hash}`
  return { path, query, hash, fullPath } as unknown as RouteLocationNormalized
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

  // Regression (SPEC-032): the middleware used to consult `window.location` on
  // EVERY navigation. The browser URL only catches up once a navigation
  // commits, so while confirm.vue was navigating away it still read
  // `/confirm?code=...` — and bounced the visitor straight back to /confirm,
  // stranding a signed-in Google user on the "Confirming your session" spinner.
  describe('stale browser URL', () => {
    const originalLocation = window.location

    function stubLocation(pathname: string, search: string, hash = '') {
      // @ts-expect-error - reassigning location is allowed in the test DOM
      delete window.location
      // @ts-expect-error - a partial Location is enough for this middleware
      window.location = { ...originalLocation, pathname, search, hash }
    }

    afterEach(() => {
      // @ts-expect-error - restore the real Location object
      delete window.location
      // @ts-expect-error - restore the real Location object
      window.location = originalLocation
    })

    it('does not bounce back when leaving /confirm while the URL still carries the code', async () => {
      const middleware = (await import('~/middleware/auth-redirect.global')).default
      stubLocation('/confirm', '?flow=oauth&code=test-code-123')

      const result = middleware(
        makeRoute('/'),
        makeRoute('/confirm', { flow: 'oauth', code: 'test-code-123' })
      )

      expect(result).toBeUndefined()
      expect(navigateToMock).not.toHaveBeenCalled()
    })

    it('ignores a stale window.location on an in-app navigation', async () => {
      const middleware = (await import('~/middleware/auth-redirect.global')).default
      stubLocation('/items', '?code=test-code-123')

      const result = middleware(makeRoute('/orders'), makeRoute('/items'))

      expect(result).toBeUndefined()
      expect(navigateToMock).not.toHaveBeenCalled()
    })

    it('still reads window.location on the initial navigation', async () => {
      const middleware = (await import('~/middleware/auth-redirect.global')).default
      stubLocation('/', '', '#access_token=abc&refresh_token=def')

      middleware(makeRoute('/'), makeRoute('/'))

      expect(navigateToMock).toHaveBeenCalledWith(expect.objectContaining({ path: '/confirm' }))
    })
  })
})
