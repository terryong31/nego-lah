import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import type { RouteLocationNormalized } from 'vue-router'
import authMiddleware from '~/middleware/auth'
import { makeAuthStub } from '../helpers/auth'

const { navigateToMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn((path: string) => ({ __redirect: path }))
}))

const userRef = ref<{ id: string, email: string } | null>(null)
const authStub = makeAuthStub(userRef)

mockNuxtImport('useAuth', () => () => authStub)
mockNuxtImport('navigateTo', () => navigateToMock)

function makeRoute(path = '/dashboard'): RouteLocationNormalized {
  return { path, fullPath: path } as RouteLocationNormalized
}

describe('middleware/auth', () => {
  beforeEach(() => {
    navigateToMock.mockClear()
    authStub.fetchSession.mockClear().mockImplementation(async () => userRef.value)
    authStub.ready.value = true
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

  it('allows navigation through (returns nothing) when a user is present', async () => {
    userRef.value = { id: 'u1', email: 'user@example.com' }

    const result = await authMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })

  it('asks the server when the session has not been resolved yet', async () => {
    // SPEC-093: the session is an httpOnly cookie, so "not asked yet" and "not
    // signed in" look identical from here. `ready` is what tells them apart —
    // guessing wrong would bounce a signed-in buyer to /login on a hard refresh.
    authStub.ready.value = false
    authStub.fetchSession.mockImplementation(async () => {
      userRef.value = { id: 'u2', email: 'session@example.com' }
      return userRef.value
    })

    const result = await authMiddleware(makeRoute(), makeRoute('/'))

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })
})
