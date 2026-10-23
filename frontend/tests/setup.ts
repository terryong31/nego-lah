import { afterEach, beforeAll, beforeEach, vi } from 'vitest'

// The item page renders <MDC>, which imports MDCRenderer. Any test that lands
// the test app's router on `/items/…` (a `route:` mount option, a clicked
// link, a redirect) makes the router lazy-load that page. Nothing awaits the
// import, so it can resolve after the file's environment is torn down, and
// Vitest fails the whole run with an EnvironmentTeardownError blamed on
// whichever file is running then: every test green, CI red. Loading the page
// up front turns the router's import into a cache hit.
beforeAll(() => import('~/pages/items/[id].vue'))

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
