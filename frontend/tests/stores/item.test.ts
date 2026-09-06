/**
 * SPEC-041: useItemStore — Scenarios 4–6
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useItemStore } from '~/stores/item'

const ITEM_ID = 'item-abc'
const BASE_ITEM = {
  item_id: ITEM_ID,
  name: 'AirPods Max',
  price: 1025,
  status: 'available',
  images: '[]'
}

function makeStore(returnValue: object) {
  const fetchFn = vi.fn().mockResolvedValue(returnValue)
  const store = useItemStore(fetchFn)
  return { store, fetchFn }
}

describe('stores/item.ts — useItemStore', () => {
  beforeEach(() => {
    // Reset shared useState between tests.
    useItemStore().clear()
  })

  // Scenario 4 — fetchIfMissing deduplication
  describe('fetchIfMissing', () => {
    it('calls the API exactly once even when called twice with the same item_id', async () => {
      const { store, fetchFn } = makeStore({ ...BASE_ITEM })

      await store.fetchIfMissing(ITEM_ID)
      await store.fetchIfMissing(ITEM_ID)

      expect(fetchFn).toHaveBeenCalledTimes(1)
    })

    it('populates the store from the API response including a pre-existing discount', async () => {
      const { store } = makeStore({ ...BASE_ITEM, discounted_price: 900 })

      await store.fetchIfMissing(ITEM_ID)

      expect(store.getItem(ITEM_ID)?.item.price).toBe(1025)
      expect(store.getItem(ITEM_ID)?.discountedPrice).toBe(900)
    })
  })

  describe('refetch', () => {
    it('calls the API again even when an entry already exists, overwriting it', async () => {
      const fetchFn = vi.fn()
        .mockResolvedValueOnce({ ...BASE_ITEM, status: 'available' })
        .mockResolvedValueOnce({ ...BASE_ITEM, status: 'sold' })
      const store = useItemStore(fetchFn)

      await store.fetchIfMissing(ITEM_ID)
      await store.refetch(ITEM_ID)

      expect(fetchFn).toHaveBeenCalledTimes(2)
      expect(store.getItem(ITEM_ID)?.item.status).toBe('sold')
    })

    it('leaves the existing cache entry in place when the refetch fails', async () => {
      const fetchFn = vi.fn()
        .mockResolvedValueOnce({ ...BASE_ITEM })
        .mockRejectedValueOnce(new Error('network error'))
      const store = useItemStore(fetchFn)

      await store.fetchIfMissing(ITEM_ID)
      await store.refetch(ITEM_ID)

      expect(store.getItem(ITEM_ID)?.item.price).toBe(1025)
    })
  })

  // Scenario 5 — applyDiscount reactive patch
  describe('applyDiscount', () => {
    it('patches discountedPrice; effectivePrice returns the discount; hasDiscount becomes true', async () => {
      const { store } = makeStore({ ...BASE_ITEM })
      await store.fetchIfMissing(ITEM_ID)

      store.applyDiscount(ITEM_ID, 900)

      expect(store.getItem(ITEM_ID)?.discountedPrice).toBe(900)
      expect(store.effectivePrice(ITEM_ID)).toBe(900)
      expect(store.hasDiscount(ITEM_ID)).toBe(true)
    })

    it('is a no-op for an unknown item_id (store not yet seeded)', () => {
      const store = useItemStore()
      expect(() => store.applyDiscount('unknown', 500)).not.toThrow()
    })
  })

  // Scenario 6 — pre-discounted item loaded from API on cold start
  describe('pre-existing discount on load', () => {
    it('effectivePrice reflects discounted_price from API without any SSE event', async () => {
      const { store } = makeStore({ ...BASE_ITEM, discounted_price: 850 })

      await store.fetchIfMissing(ITEM_ID)

      expect(store.effectivePrice(ITEM_ID)).toBe(850)
      expect(store.hasDiscount(ITEM_ID)).toBe(true)
      expect(store.discountPercent(ITEM_ID)).toBe(17)
    })

    it('effectivePrice falls back to listed price when no discount exists', async () => {
      const { store } = makeStore({ ...BASE_ITEM })

      await store.fetchIfMissing(ITEM_ID)

      expect(store.effectivePrice(ITEM_ID)).toBe(1025)
      expect(store.hasDiscount(ITEM_ID)).toBe(false)
      expect(store.discountPercent(ITEM_ID)).toBe(0)
    })
  })
})
