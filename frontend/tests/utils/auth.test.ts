import { describe, expect, it } from 'vitest'
import { isAuthGuarded, loginRedirect, resolveAvatarUrl, safeRedirectPath } from '~/utils/auth'

describe('utils/auth.ts - isAuthGuarded', () => {
  it('returns true for routes with meta.middleware = "auth"', () => {
    expect(isAuthGuarded({ path: '/orders', meta: { middleware: 'auth' } })).toBe(true)
    expect(isAuthGuarded({ path: '/chat', meta: { middleware: 'auth' } })).toBe(true)
    expect(isAuthGuarded({ path: '/profile', meta: { middleware: 'auth' } })).toBe(true)
    expect(isAuthGuarded({ path: '/some-new-guarded-page', meta: { middleware: 'auth' } })).toBe(true)
  })

  it('returns true for routes with meta.middleware = "admin-auth"', () => {
    expect(isAuthGuarded({ path: '/_console', meta: { middleware: 'admin-auth' } })).toBe(true)
    expect(isAuthGuarded({ path: '/_console/users', meta: { middleware: 'admin-auth' } })).toBe(true)
    expect(isAuthGuarded({ path: '/_console/items', meta: { middleware: 'admin-auth' } })).toBe(true)
  })

  it('returns true for routes with array middleware containing "auth" or "admin-auth"', () => {
    expect(isAuthGuarded({ path: '/custom', meta: { middleware: ['logging', 'auth'] } })).toBe(true)
    expect(isAuthGuarded({ path: '/custom-admin', meta: { middleware: ['admin-auth', 'other'] } })).toBe(true)
  })

  it('returns true when matched records have auth middleware', () => {
    expect(isAuthGuarded({
      path: '/nested/page',
      matched: [{ meta: { middleware: 'auth' } }]
    })).toBe(true)
  })

  it('falls back to path prefixes for known guarded routes even without meta', () => {
    expect(isAuthGuarded({ path: '/orders' })).toBe(true)
    expect(isAuthGuarded({ path: '/orders/123' })).toBe(true)
    expect(isAuthGuarded({ path: '/chat' })).toBe(true)
    expect(isAuthGuarded({ path: '/chat?item_id=123' })).toBe(true)
    expect(isAuthGuarded({ path: '/profile' })).toBe(true)
    expect(isAuthGuarded({ path: '/profile/settings' })).toBe(true)
    expect(isAuthGuarded({ path: '/_console' })).toBe(true)
    expect(isAuthGuarded({ path: '/_console/chats' })).toBe(true)
  })

  it('returns false for admin login page /_console/login', () => {
    expect(isAuthGuarded({ path: '/_console/login' })).toBe(false)
  })

  it('returns false for public routes', () => {
    expect(isAuthGuarded({ path: '/' })).toBe(false)
    expect(isAuthGuarded({ path: '/items' })).toBe(false)
    expect(isAuthGuarded({ path: '/items/item-123' })).toBe(false)
    expect(isAuthGuarded({ path: '/terms' })).toBe(false)
    expect(isAuthGuarded({ path: '/privacy' })).toBe(false)
    expect(isAuthGuarded({ path: '/login' })).toBe(false)
    expect(isAuthGuarded({ path: '/register' })).toBe(false)
    expect(isAuthGuarded({ path: '/forgot-password' })).toBe(false)
    expect(isAuthGuarded({ path: '/reset-password' })).toBe(false)
  })

  it('returns false when given a null or undefined route-like object', () => {
    // @ts-expect-error test undefined/null safety
    expect(isAuthGuarded(null)).toBe(false)
    // @ts-expect-error test undefined/null safety
    expect(isAuthGuarded(undefined)).toBe(false)
  })
})

describe('utils/auth.ts - safeRedirectPath', () => {
  it('accepts a same-origin path, preserving its query string and hash', () => {
    expect(safeRedirectPath('/chat')).toBe('/chat')
    expect(safeRedirectPath('/chat?item_id=item-1')).toBe('/chat?item_id=item-1')
    expect(safeRedirectPath('/items/item-1#reviews')).toBe('/items/item-1#reviews')
  })

  it('rejects protocol-relative and absolute URLs (open-redirect guard)', () => {
    expect(safeRedirectPath('//evil.com')).toBeNull()
    expect(safeRedirectPath('//evil.com/chat')).toBeNull()
    expect(safeRedirectPath('/\\evil.com')).toBeNull()
    expect(safeRedirectPath('https://evil.com')).toBeNull()
    expect(safeRedirectPath('http://evil.com')).toBeNull()
    expect(safeRedirectPath('javascript:alert(1)')).toBeNull()
  })

  it('rejects relative paths, empty strings and non-string values', () => {
    expect(safeRedirectPath('chat')).toBeNull()
    expect(safeRedirectPath('')).toBeNull()
    expect(safeRedirectPath(undefined)).toBeNull()
    expect(safeRedirectPath(null)).toBeNull()
    expect(safeRedirectPath(['/chat'])).toBeNull()
    expect(safeRedirectPath(42)).toBeNull()
  })
})

describe('utils/auth.ts - loginRedirect', () => {
  it('carries a worthwhile target through as the redirect query', () => {
    expect(loginRedirect('/chat?item_id=item-1')).toEqual({
      path: '/login',
      query: { redirect: '/chat?item_id=item-1' }
    })
    expect(loginRedirect('/orders')).toEqual({ path: '/login', query: { redirect: '/orders' } })
  })

  it('omits the query for targets not worth returning to', () => {
    for (const path of ['/', '/login', '/register', '/forgot-password', '/reset-password', '/confirm']) {
      expect(loginRedirect(path)).toEqual({ path: '/login' })
    }
  })

  it('ignores the query string when deciding whether a target is worth returning to', () => {
    expect(loginRedirect('/login?redirect=%2Fchat')).toEqual({ path: '/login' })
    expect(loginRedirect('/confirm?code=abc')).toEqual({ path: '/login' })
  })

  it('omits the query for unsafe or missing targets', () => {
    expect(loginRedirect('//evil.com')).toEqual({ path: '/login' })
    expect(loginRedirect('https://evil.com')).toEqual({ path: '/login' })
    expect(loginRedirect(undefined)).toEqual({ path: '/login' })
    expect(loginRedirect(null)).toEqual({ path: '/login' })
  })
})

describe('utils/auth.ts - resolveAvatarUrl', () => {
  // Supabase re-syncs user_metadata from the identity provider on every OAuth
  // sign-in, so `avatar_url` belongs to Google. The self-uploaded avatar lives
  // under `custom_avatar_url` and has to win wherever an avatar is displayed.
  it('prefers a self-uploaded avatar over the provider photo', () => {
    expect(resolveAvatarUrl({
      user_metadata: {
        custom_avatar_url: 'https://cdn.negolah.my/avatars/u1/mine.png',
        avatar_url: 'https://lh3.googleusercontent.com/a/google-photo'
      }
    })).toBe('https://cdn.negolah.my/avatars/u1/mine.png')
  })

  it('falls back to the provider photo when nothing was uploaded', () => {
    expect(resolveAvatarUrl({
      user_metadata: { avatar_url: 'https://lh3.googleusercontent.com/a/google-photo' }
    })).toBe('https://lh3.googleusercontent.com/a/google-photo')
  })

  it('returns undefined when neither key is set', () => {
    expect(resolveAvatarUrl({ user_metadata: {} })).toBeUndefined()
    expect(resolveAvatarUrl({})).toBeUndefined()
    expect(resolveAvatarUrl(null)).toBeUndefined()
    expect(resolveAvatarUrl(undefined)).toBeUndefined()
  })

  it('treats empty strings as absent so UAvatar falls through to initials', () => {
    expect(resolveAvatarUrl({
      user_metadata: { custom_avatar_url: '', avatar_url: '' }
    })).toBeUndefined()
    expect(resolveAvatarUrl({
      user_metadata: { custom_avatar_url: '', avatar_url: 'https://lh3.googleusercontent.com/a/p' }
    })).toBe('https://lh3.googleusercontent.com/a/p')
  })
})
