import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import SuccessPage from '~/pages/checkout/success.vue'

const { userRef } = vi.hoisted(() => ({
  userRef: { __v_isRef: true, value: null as Record<string, unknown> | null }
}))
const { toastAddMock } = vi.hoisted(() => ({ toastAddMock: vi.fn() }))

const callMock = vi.fn()

mockNuxtImport('useApi', () => () => ({ call: callMock }))
mockNuxtImport('useSupabaseUser', () => () => userRef)
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))

// mountSuspended's `route` option (raw path+querystring, resolved via a real
// router.replace()) does not reliably land in this page's `useRoute()` by the
// time onMounted runs in this @nuxt/test-utils version. Use the same proven
// direct-mock pattern as tests/pages/items/index.test.ts instead: a reactive
// stub returned by a mocked useRoute(), whose `query` we set per test.
const routeStub = reactive<{ query: Record<string, string | undefined> }>({ query: {} })
mockNuxtImport('useRoute', () => () => routeStub)

// Tracks the wrapper mounted by the current test so afterEach can dispose of
// it before the next test mounts a fresh instance (see items/index.test.ts
// for the rationale on why leaving a stale instance mounted is dangerous).
let activeWrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

async function mountAt(query: Record<string, string | undefined>) {
  routeStub.query = query
  activeWrapper = await mountSuspended(SuccessPage)
  return activeWrapper
}

describe('pages/checkout/success.vue', () => {
  beforeEach(() => {
    userRef.value = { id: 'u1', email: 'buyer@example.com' }
    callMock.mockReset()
    toastAddMock.mockClear()
  })

  afterEach(() => {
    activeWrapper?.unmount()
    activeWrapper = undefined
    vi.useRealTimers()
  })

  describe('missing item_id', () => {
    it('shows the error state immediately and never calls the API', async () => {
      const wrapper = await mountAt({})
      await flushPromises()

      expect(wrapper.text()).toContain('Verification Error')
      expect(wrapper.text()).toContain('Missing item identifier in confirmation.')
      expect(callMock).not.toHaveBeenCalled()
      expect(toastAddMock).not.toHaveBeenCalled()
    })
  })

  describe('with session_id (Branch A: backend verifies with Stripe directly)', () => {
    it('shows the "Verifying Transaction" UI before the call resolves', async () => {
      let resolveCall!: (value: { status?: string }) => void
      callMock.mockImplementation(() => new Promise((resolve) => {
        resolveCall = resolve
      }))

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })

      expect(wrapper.text()).toContain('Verifying Transaction')
      expect(wrapper.text()).not.toContain('Purchase Successful!')

      resolveCall({ status: 'success' })
      await flushPromises()
    })

    it('calls confirm-payment with item_id, user_id and session_id', async () => {
      callMock.mockResolvedValue({ status: 'success' })

      await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(callMock).toHaveBeenCalledWith('/payment/confirm-payment', {
        method: 'POST',
        query: { item_id: 'item-1', user_id: 'u1', session_id: 'sess-1' }
      })
    })

    it('shows the success UI and a success toast when the backend confirms success', async () => {
      callMock.mockResolvedValue({ status: 'success' })

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Purchase Successful!')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Payment confirmed!',
        description: 'Your order has been recorded successfully.',
        color: 'success'
      })
    })

    it('shows the refunded UI and a warning toast when the backend reports status "refunded"', async () => {
      callMock.mockResolvedValue({ status: 'refunded' })

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Item No Longer Available')
      expect(wrapper.text()).toContain('fully refunded')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Item no longer available',
        description: 'Someone bought it just before your payment. You have been fully refunded.',
        color: 'warning'
      })
    })

    it('treats an error whose data.detail mentions "already_sold" as a success (webhook won the race)', async () => {
      callMock.mockRejectedValue({ data: { detail: 'already_sold: item was purchased by the webhook first' } })

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Purchase Successful!')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Payment confirmed!',
        description: 'Your order has been recorded successfully.',
        color: 'success'
      })
    })

    it('treats an error whose data.status is "already_sold" as a success', async () => {
      callMock.mockRejectedValue({ data: { status: 'already_sold' } })

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Purchase Successful!')
    })

    it('shows the generic failure message (from data.detail) and an error toast for other errors', async () => {
      callMock.mockRejectedValue({ data: { detail: 'Your card was declined.' } })

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Verification Error')
      expect(wrapper.text()).toContain('Your card was declined.')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Confirmation failed',
        description: 'Your card was declined.',
        color: 'error'
      })
    })

    it('falls back to err.message when there is no data.detail', async () => {
      callMock.mockRejectedValue(new Error('Network error'))

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Network error')
    })

    it('falls back to a generic message when neither data.detail nor message are present', async () => {
      callMock.mockRejectedValue({})

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Payment confirmation failed.')
    })

    it('stops showing the "Verifying Transaction" UI once confirmation finishes (success or failure)', async () => {
      callMock.mockRejectedValue({})

      const wrapper = await mountAt({ item_id: 'item-1', session_id: 'sess-1' })
      await flushPromises()

      expect(wrapper.text()).not.toContain('Verifying Transaction')
    })
  })

  describe('without session_id (Branch B: poll this user\'s orders as a PaymentLink fallback)', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    it('polls GET /payment/orders/user/:id for the current user', async () => {
      callMock.mockResolvedValue({ orders: [] })

      await mountAt({ item_id: 'item-1' })
      await flushPromises()

      expect(callMock).toHaveBeenCalledWith('/payment/orders/user/u1')
    })

    it('finds a matching order partway through polling and applies the success outcome, stopping early', async () => {
      let attempts = 0
      callMock.mockImplementation(async () => {
        attempts++
        if (attempts === 3) {
          return { orders: [{ item_id: 'item-1', status: 'paid' }] }
        }
        return { orders: [{ item_id: 'some-other-item', status: 'paid' }] }
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises() // attempt 1 (no match) -> starts the 2s sleep

      await vi.advanceTimersByTimeAsync(2000) // attempt 2 (no match) -> starts the 2s sleep
      await vi.advanceTimersByTimeAsync(2000) // attempt 3 (match) -> breaks, no further sleep
      await flushPromises()

      // Exactly 3 calls to the polling endpoint - the loop broke early and never
      // reached the confirm-payment fallback.
      expect(callMock).toHaveBeenCalledTimes(3)
      callMock.mock.calls.forEach((call) => {
        expect(call[0]).toBe('/payment/orders/user/u1')
      })
      expect(wrapper.text()).toContain('Purchase Successful!')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Payment confirmed!',
        description: 'Your order has been recorded successfully.',
        color: 'success'
      })
    })

    it('applies the refunded outcome when the matching order\'s own status is "refunded"', async () => {
      callMock
        .mockResolvedValueOnce({ orders: [] })
        .mockResolvedValueOnce({ orders: [{ item_id: 'item-1', status: 'refunded' }] })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(callMock).toHaveBeenCalledTimes(2)
      expect(wrapper.text()).toContain('Item No Longer Available')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Item no longer available',
        description: 'Someone bought it just before your payment. You have been fully refunded.',
        color: 'warning'
      })
    })

    it('treats any non-"refunded" order status (e.g. "paid") as a success outcome', async () => {
      callMock.mockResolvedValue({ orders: [{ item_id: 'item-1', status: 'paid' }] })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()

      expect(wrapper.text()).toContain('Purchase Successful!')
    })

    it('keeps polling when an individual attempt throws, and can still find a match on a later attempt', async () => {
      let attempts = 0
      callMock.mockImplementation(async () => {
        attempts++
        if (attempts === 1) throw new Error('transient network error')
        if (attempts === 2) return { orders: [{ item_id: 'item-1', status: 'paid' }] }
        throw new Error('should not be called again')
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises() // attempt 1 throws -> caught, starts the 2s sleep

      await vi.advanceTimersByTimeAsync(2000) // attempt 2 matches -> breaks
      await flushPromises()

      expect(callMock).toHaveBeenCalledTimes(2)
      expect(wrapper.text()).toContain('Purchase Successful!')
    })

    it('exhausts all 6 polling attempts (each 2s apart) then falls back to POST confirm-payment, succeeding', async () => {
      callMock.mockImplementation(async (path: string) => {
        if (path === '/payment/orders/user/u1') return { orders: [] }
        if (path === '/payment/confirm-payment') return { status: 'success' }
        throw new Error(`unexpected call: ${path}`)
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()

      // 6 attempts, each followed by a 2s sleep before the next one/the fallback.
      for (let i = 0; i < 6; i++) {
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
      }

      // 6 polling calls + exactly 1 fallback confirm-payment call.
      expect(callMock).toHaveBeenCalledTimes(7)
      expect(callMock.mock.calls.slice(0, 6).every(call => call[0] === '/payment/orders/user/u1')).toBe(true)
      expect(callMock).toHaveBeenLastCalledWith('/payment/confirm-payment', {
        method: 'POST',
        query: { item_id: 'item-1', user_id: 'u1' }
      })
      expect(wrapper.text()).toContain('Purchase Successful!')
    })

    it('exhausts all attempts, and treats a fallback confirm-payment "already_sold" status as success too', async () => {
      callMock.mockImplementation(async (path: string) => {
        if (path === '/payment/orders/user/u1') return { orders: [] }
        if (path === '/payment/confirm-payment') return { status: 'already_sold' }
        throw new Error(`unexpected call: ${path}`)
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()
      for (let i = 0; i < 6; i++) {
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
      }

      expect(wrapper.text()).toContain('Purchase Successful!')
    })

    it('exhausts all attempts, then shows the "verification pending" message when the fallback resolves but does not confirm', async () => {
      callMock.mockImplementation(async (path: string) => {
        if (path === '/payment/orders/user/u1') return { orders: [] }
        if (path === '/payment/confirm-payment') return { status: 'pending' }
        throw new Error(`unexpected call: ${path}`)
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()
      for (let i = 0; i < 6; i++) {
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
      }

      expect(wrapper.text()).toContain('Verification Error')
      expect(wrapper.text()).toContain('We could not confirm your payment yet.')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Verification pending',
        description: 'Could not confirm payment automatically.',
        color: 'warning'
      })
    })

    it('exhausts all attempts, then shows the "could not verify automatically" message when the fallback itself throws', async () => {
      callMock.mockImplementation(async (path: string) => {
        if (path === '/payment/orders/user/u1') return { orders: [] }
        if (path === '/payment/confirm-payment') throw new Error('confirm-payment failed')
        throw new Error(`unexpected call: ${path}`)
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()
      for (let i = 0; i < 6; i++) {
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
      }

      expect(wrapper.text()).toContain('Verification Error')
      expect(wrapper.text()).toContain('We could not verify your payment automatically.')
      expect(toastAddMock).toHaveBeenCalledWith({
        title: 'Verification pending',
        description: 'Could not confirm payment automatically.',
        color: 'warning'
      })
    })

    it('ends confirming state once the fallback path completes', async () => {
      callMock.mockImplementation(async (path: string) => {
        if (path === '/payment/orders/user/u1') return { orders: [] }
        return { status: 'success' }
      })

      const wrapper = await mountAt({ item_id: 'item-1' })
      await flushPromises()
      for (let i = 0; i < 6; i++) {
        await vi.advanceTimersByTimeAsync(2000)
        await flushPromises()
      }

      expect(wrapper.text()).not.toContain('Verifying Transaction')
    })
  })
})
