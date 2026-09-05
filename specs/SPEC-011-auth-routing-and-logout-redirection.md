---
id: SPEC-011
title: Auth Routing and Context-Aware Logout Redirection
status: complete
priority: medium
created: 2026-09-05
tags: [frontend, nuxt, auth, routing, navigation]
assigned: agent
---

# Context & Objectives
Previously, clicking "Sign Out" in the application header unconditionally redirected the user to the home page (`/`) via `router.push('/')`. For users browsing public pages (such as item detail pages `/items/[id]`, the storefront `/`, terms, or privacy pages), signing out disrupted their browsing context.

The objective is to refine the sign-out flow so that logout does NOT redirect to `/` unless the user is on an auth-guarded page (e.g. `/orders`, `/chat`, `/profile`, or `/_console/*`). On public pages, the user stays on their current page with the authentication state reset reactively.

# Acceptance Criteria
- [x] Determine whether the current route is auth-guarded via route metadata (`middleware: 'auth' | 'admin-auth'`), matched records, and protected route path patterns (`/orders`, `/chat`, `/profile`, `/_console/*`).
- [x] When signing out from an auth-guarded page, successfully sign out and redirect to `/`.
- [x] When signing out from a public page (e.g., `/items/[id]`, `/`, `/terms`, `/privacy`), successfully sign out and remain on the current route without redirecting to `/`.
- [x] Maintain toast notifications for successful sign-out and sign-out errors.
- [x] Automated tests assert both auth-guarded redirect and public non-redirect behaviors.

# Technical Design & Contracts
- **Route Guard Detection:**
  A helper function evaluates if the current route has `auth` or `admin-auth` middleware or matches protected prefixes:
  ```ts
  function isAuthGuarded(route: RouteLocationNormalizedLoaded): boolean {
    const mw = route.meta?.middleware
    if (typeof mw === 'string' && (mw === 'auth' || mw === 'admin-auth')) return true
    if (Array.isArray(mw) && (mw.includes('auth') || mw.includes('admin-auth'))) return true
    if (route.matched?.some(record => {
      const rmw = record.meta?.middleware
      return rmw === 'auth' || rmw === 'admin-auth' || (Array.isArray(rmw) && (rmw.includes('auth') || rmw.includes('admin-auth')))
    })) return true
    const protectedPrefixes = ['/orders', '/chat', '/profile', '/_console']
    if (route.path === '/_console/login') return false
    return protectedPrefixes.some(prefix => route.path === prefix || route.path.startsWith(`${prefix}/`))
  }
  ```
- **Sign Out Handler in `AppHeader.vue`:**
  ```ts
  const { error } = await supabase.auth.signOut()
  if (error) {
    toast.add({ title: t('header.logoutFailed'), description: error.message, color: 'error' })
  } else {
    toast.add({ title: t('header.signedOut'), description: t('header.seeYouAgain'), color: 'success' })
    if (isAuthGuarded(route)) {
      router.push('/')
    }
  }
  ```

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** Signing out on an auth-guarded route (`/profile`) triggers `router.push('/')`.
- [x] **Scenario 2:** Signing out on a public route (`/items/test-item` or `/`) does NOT trigger `router.push('/')`.
- [x] **Scenario 3:** `isAuthGuarded` correctly identifies `/orders`, `/chat`, `/profile`, `/_console` as guarded and `/`, `/items/1`, `/terms`, `/privacy` as unguarded.

# Implementation Files
- `frontend/app/utils/auth.ts` - Implement `isAuthGuarded` route check utility.
- `frontend/app/components/AppHeader.vue` - Add route guard check and conditional redirect on sign out.
- `frontend/tests/utils/auth.test.ts` - Unit tests for `isAuthGuarded` utility.
- `frontend/tests/components/AppHeader.test.ts` - Add unit tests for guarded vs public route sign out.
