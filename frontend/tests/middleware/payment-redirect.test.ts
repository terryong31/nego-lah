import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'

const { navigateToMock } = vi.hoisted(() => ({ navigateToMock: vi.fn() }))

mockNuxtImport('navigateTo', () => navigateToMock)

beforeEach(() => {
  navigateToMock.mockClear()
})

// Helper to build a minimal fake route object, similar in shape to what
// vue-router / Nuxt would pass as `to`.
function makeRoute(path: string, query: Record<string, string | undefined> = {}) {
  return { path, query } as unknown as RouteLocationNormalized
}

describe('middleware/payment-redirect.global.ts', () => {
  it('does nothing when there is no payment query param', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    const result = middleware(makeRoute('/'), makeRoute('/'))

    expect(result).toBeUndefined()
    expect(navigateToMock).not.toHaveBeenCalled()
  })

  it('redirects to /checkout/success with item_id and session_id when payment=success', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    middleware(
      makeRoute('/', { payment: 'success', item_id: 'item-123', session_id: 'sess-456' }),
      makeRoute('/')
    )

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/checkout/success',
      query: {
        item_id: 'item-123',
        session_id: 'sess-456'
      }
    })
  })

  it('redirects to /checkout/success even when item_id/session_id are missing', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    middleware(makeRoute('/some-page', { payment: 'success' }), makeRoute('/'))

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/checkout/success',
      query: {
        item_id: undefined,
        session_id: undefined
      }
    })
  })

  it('redirects to /checkout/cancel when payment=cancelled', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    middleware(makeRoute('/', { payment: 'cancelled' }), makeRoute('/'))

    expect(navigateToMock).toHaveBeenCalledWith('/checkout/cancel')
  })

  it('does not redirect for an unrecognized payment value', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    const result = middleware(makeRoute('/', { payment: 'pending' }), makeRoute('/'))

    expect(result).toBeUndefined()
    expect(navigateToMock).not.toHaveBeenCalled()
  })

  it('does not redirect when already on a /checkout/ path, even with payment=success', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    const result = middleware(
      makeRoute('/checkout/success', { payment: 'success', item_id: 'x', session_id: 'y' }),
      makeRoute('/')
    )

    expect(result).toBeUndefined()
    expect(navigateToMock).not.toHaveBeenCalled()
  })

  it('does not redirect when already on a /checkout/ path with payment=cancelled', async () => {
    const middleware = (await import('~/middleware/payment-redirect.global')).default

    const result = middleware(makeRoute('/checkout/cancel', { payment: 'cancelled' }), makeRoute('/'))

    expect(result).toBeUndefined()
    expect(navigateToMock).not.toHaveBeenCalled()
  })
})
