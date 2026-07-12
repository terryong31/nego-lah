import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import type { RouteLocationNormalized } from 'vue-router'
import authMiddleware from '~/middleware/auth'

const { navigateToMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn((path: string) => ({ __redirect: path }))
}))

const userRef = ref<{ id: string, email: string } | null>(null)

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('navigateTo', () => navigateToMock)

function makeRoute(path = '/dashboard'): RouteLocationNormalized {
  return { path } as RouteLocationNormalized
}

describe('middleware/auth', () => {
  beforeEach(() => {
    navigateToMock.mockClear()
    userRef.value = null
  })

  it('redirects to /login when there is no authenticated user', () => {
    userRef.value = null

    const result = authMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).toHaveBeenCalledWith('/login')
    expect(result).toEqual({ __redirect: '/login' })
  })

  it('allows navigation through (returns nothing) when a user is present', () => {
    userRef.value = { id: 'u1', email: 'user@example.com' }

    const result = authMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })
})
