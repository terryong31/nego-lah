/**
 * SPEC-041: Item store — write-through cache for item data.
 *
 * Implemented as a module-level singleton composable (useState pattern) rather
 * than Pinia, since Pinia is not a registered Nuxt module in this project.
 * `useState` gives us SSR-safe reactive state shared across the app.
 *
 * Responsibilities:
 * - `fetchIfMissing(itemId)` fetches GET /items/:id exactly once per item per
 *   session. Subsequent calls for the same ID are no-ops.
 * - `applyDiscount(itemId, price)` patches discountedPrice in place when the
 *   backend emits a `data-discount` SSE frame. No API call is made.
 * - Getters (`effectivePrice`, `hasDiscount`, `discountPercent`) expose computed
 *   price state to components.
 *
 * Keyed by item_id so multiple tabs / future multi-item chats work without a
 * refactor.
 */

export interface StoreItem {
  item_id: string
  name: string
  price: number
  discounted_price?: number
  status?: string
  images?: string
  translations?: Record<string, ItemTranslation>
  [key: string]: unknown
}

export interface ItemState {
  item: StoreItem
  discountedPrice: number | null
}

// Injected fetch function type — overridable in tests.
type FetchFn = (itemId: string) => Promise<StoreItem>

export function useItemStore(fetchFn?: FetchFn) {
  const _items = useState<Map<string, ItemState>>('item-store', () => new Map())

  // ---------------------------------------------------------------------------
  // Internal fetch — uses injected fn in tests, real useApi in production.
  // ---------------------------------------------------------------------------
  async function _fetchItem(itemId: string): Promise<StoreItem> {
    if (fetchFn) return fetchFn(itemId)
    const { call } = useApi()
    return call<StoreItem>(`/items/${itemId}`)
  }

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  /** Shared fetch-and-cache used by both `fetchIfMissing` and `refetch`. */
  async function _load(itemId: string): Promise<void> {
    try {
      const raw = await _fetchItem(itemId)
      _items.value.set(itemId, {
        item: raw,
        discountedPrice: raw.discounted_price != null ? raw.discounted_price : null
      })
    } catch {
      // Item may be gone or auth expired — leave whatever was already
      // cached in place; a caller showing a header/card just won't update.
    }
  }

  /** Fetch and cache the item if not already present. Idempotent. */
  async function fetchIfMissing(itemId: string): Promise<void> {
    if (_items.value.has(itemId)) return
    await _load(itemId)
  }

  /**
   * Unconditionally refetch and overwrite the cached item, even if an entry
   * already exists. Unlike `fetchIfMissing`, this is NOT a no-op on a cache
   * hit — use it when the caller knows the cache may be stale (e.g. the item
   * detail page re-fetching after a 409 "just sold" checkout response).
   */
  async function refetch(itemId: string): Promise<void> {
    await _load(itemId)
  }

  /**
   * Patch the discounted price for a cached item.
   * Called by the chat SSE handler when a `data-discount` frame arrives.
   * No-op if the item hasn't been fetched yet.
   */
  function applyDiscount(itemId: string, price: number): void {
    const state = _items.value.get(itemId)
    if (!state) return
    state.discountedPrice = price
  }

  /** Reset all cached items — for test isolation. */
  function clear(): void {
    _items.value = new Map()
  }

  // ---------------------------------------------------------------------------
  // Getters
  // ---------------------------------------------------------------------------

  function getItem(itemId: string): ItemState | undefined {
    return _items.value.get(itemId)
  }

  /**
   * The price/discount getters below take an `itemId` (matching this store's
   * own keying) and exist to satisfy this store's own contract. Real page
   * components (`chat.vue`, `ItemCard.vue`, `pages/items/[id].vue`) don't call
   * these directly — they read `getItem(itemId)` and pass the merged
   * `{ price, discounted_price }` shape to the shared, item-shaped helpers in
   * `~/utils/pricing.ts` instead, so there's exactly one place the actual
   * discount math lives. Keep these two in sync if that math ever changes.
   */

  /** The price the buyer would actually pay right now. */
  function effectivePrice(itemId: string): number {
    const state = _items.value.get(itemId)
    if (!state) return 0
    const { item, discountedPrice } = state
    if (discountedPrice != null && discountedPrice < item.price) return discountedPrice
    return item.price
  }

  /** True when there is an active negotiated price below the listed price. */
  function hasDiscount(itemId: string): boolean {
    const state = _items.value.get(itemId)
    if (!state) return false
    const { item, discountedPrice } = state
    return discountedPrice != null && discountedPrice < item.price
  }

  /** Rounded whole-number saving percentage, e.g. 17 for 1025→850. */
  function discountPercent(itemId: string): number {
    if (!hasDiscount(itemId)) return 0
    const state = _items.value.get(itemId)!
    return Math.round(((state.item.price - state.discountedPrice!) / state.item.price) * 100)
  }

  return {
    fetchIfMissing,
    refetch,
    applyDiscount,
    clear,
    getItem,
    effectivePrice,
    hasDiscount,
    discountPercent
  }
}
