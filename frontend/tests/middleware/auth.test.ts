import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import type { RouteLocationNormalized } from 'vue-router'
import authMiddleware from '~/middleware/auth'

const { navigateToMock, getSessionMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn((path: string) => ({ __redirect: path })),
  getSessionMock: vi.fn().mockResolvedValue({ data: { session: null } })
}))

const userRef = ref<{ id: string, email: string } | null>(null)

mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useSupabaseClient', () => () => ({
  auth: { getSession: getSessionMock }
}))
mockNuxtImport('navigateTo', () => navigateToMock)

function makeRoute(path = '/dashboard'): RouteLocationNormalized {
  return { path, fullPath: path } as RouteLocationNormalized
}

describe('middleware/auth', () => {
  beforeEach(() => {
    navigateToMock.mockClear()
    getSessionMock.mockReset().mockResolvedValue({ data: { session: null } })
    userRef.value = null
  })

  it('redirects to /login with redirect query when there is no authenticated user', async () => {
    userRef.value = null

    const result = await authMiddleware(makeRoute('/dashboard'), makeRoute('/'))

    expect(navigateToMock).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/dashboard' }
    })
    expect(result).toEqual({ __redirect: { path: '/login', query: { redirect: '/dashboard' } } })
  })

  it('allows navigation through (returns nothing) when a user is present in userRef', async () => {
    userRef.value = { id: 'u1', email: 'user@example.com' }

    const result = await authMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })

  it('allows navigation through when userRef is null but getSession returns an active session', async () => {
    userRef.value = null
    getSessionMock.mockResolvedValue({
      data: { session: { user: { id: 'u2', email: 'session@example.com' } } }
    })

    const result = await authMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })
})
