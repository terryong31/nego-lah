/**
 * SPEC-082 — the item store must follow the signed-in identity.
 *
 * The store is a per-tab `useState` cache of user-scoped rows: `GET /items/:id`
 * attaches `discounted_price` from the *calling* buyer's negotiated price. Sign
 * out and sign in as someone else in the same tab and nothing emptied it, so
 * `fetchIfMissing` returned on a warm entry and buyer B saw buyer A's
 * negotiated price until a hard reload.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref, type Ref } from 'vue'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { useItemStore } from '../../app/stores/item'
import plugin from '../../app/plugins/item-store-identity.client'

// `vi.hoisted` runs before this module's imports, so the ref itself is created
// per-test in beforeEach and only the holder is hoisted.
const { holder } = vi.hoisted(() => ({
  holder: { user: null as unknown as Ref<{ sub: string } | null> }
}))

mockNuxtImport('useAuth', () => {
  return () => ({ user: holder.user })
})

const ITEM_ID = 'item-abc'
const BASE_ITEM = { item_id: ITEM_ID, name: 'AirPods Max', price: 1025, status: 'available', images: '[]' }

/** Run the plugin body. A plugin defined as a bare function IS its setup. */
function runPlugin() {
  const definition = plugin as unknown as { setup?: (app: unknown) => void } | ((app: unknown) => void)
  if (typeof definition === 'function') return definition({})
  return definition.setup?.({})
}

async function cacheItemWithDiscount() {
  const fetchFn = vi.fn().mockResolvedValue({ ...BASE_ITEM, discounted_price: 850 })
  await useItemStore(fetchFn).fetchIfMissing(ITEM_ID)
}

describe('plugins/item-store-identity', () => {
  beforeEach(() => {
    holder.user = ref<{ sub: string } | null>(null)
    useItemStore().setOwner(null)
    useItemStore().clear()
  })

  it('primes the owner from the restored session, so a page that fetches next is not wiped', async () => {
    holder.user.value = { sub: 'buyer-a' }
    runPlugin()

    await cacheItemWithDiscount()
    // A `page:start` claims re-read replaces the object with the same user.
    holder.user.value = { sub: 'buyer-a' }
    await nextTick()

    expect(useItemStore().getItem(ITEM_ID)?.discountedPrice).toBe(850)
  })

  it('clears the store when a different buyer signs in', async () => {
    holder.user.value = { sub: 'buyer-a' }
    runPlugin()
    await cacheItemWithDiscount()

    holder.user.value = { sub: 'buyer-b' }
    await nextTick()

    expect(useItemStore().getItem(ITEM_ID)).toBeUndefined()
  })

  it('clears the store on sign-out', async () => {
    holder.user.value = { sub: 'buyer-a' }
    runPlugin()
    await cacheItemWithDiscount()

    holder.user.value = null
    await nextTick()

    expect(useItemStore().getItem(ITEM_ID)).toBeUndefined()
  })
})
