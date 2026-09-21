import { ref, type Ref } from 'vue'
import { vi } from 'vitest'

export interface StubUser {
  id: string
  email?: string
  user_metadata?: Record<string, unknown>
}

/**
 * A stand-in for `useAuth()`, the composable that replaced `useSupabaseUser()`
 * and `useSupabaseClient()` (SPEC-093).
 *
 * The session is an httpOnly cookie now, so there is no client to fake and no
 * token to hand out — a test controls who is signed in by writing to `userRef`,
 * which is exactly what the app does when `/auth/session` answers.
 */
export function makeAuthStub(userRef: Ref<StubUser | null>) {
  return {
    user: userRef,
    ready: ref(true),
    fetchSession: vi.fn(async () => userRef.value),
    login: vi.fn(async (email: string) => {
      userRef.value = { id: 'u1', email }
      return userRef.value
    }),
    register: vi.fn(async () => ({ confirmation_sent: true })),
    signInWithProvider: vi.fn(),
    logout: vi.fn(async () => {
      userRef.value = null
    }),
    clearSession: vi.fn(() => {
      userRef.value = null
    }),
    forgotPassword: vi.fn(async () => ({ sent: true })),
    resetPassword: vi.fn(async () => ({ updated: true }))
  }
}

/** Reset every stubbed call and sign the user out, for `beforeEach`. */
export function resetAuthStub(stub: ReturnType<typeof makeAuthStub>, userRef: Ref<StubUser | null>) {
  for (const value of Object.values(stub)) {
    if (typeof value === 'function' && 'mockClear' in value) {
      (value as ReturnType<typeof vi.fn>).mockClear()
    }
  }
  userRef.value = null
  stub.ready.value = true
}
