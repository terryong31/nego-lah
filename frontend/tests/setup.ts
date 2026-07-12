import { afterEach, beforeEach, vi } from 'vitest'

// Several admin components (AdminOrders.remove, AdminUsers.remove) gate
// destructive actions behind the native browser confirm() dialog, which
// doesn't exist by default in the test DOM. Default to "confirmed" so tests
// that don't care about the dialog itself aren't forced to stub it; tests
// that DO care can `vi.spyOn(window, 'confirm').mockReturnValueOnce(false)`.
beforeEach(() => {
  vi.stubGlobal('confirm', vi.fn(() => true))
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
