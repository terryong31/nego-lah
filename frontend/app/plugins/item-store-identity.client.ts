/**
 * SPEC-082: keep the item store scoped to the buyer who is actually signed in.
 *
 * `useItemStore` caches user-scoped rows — `GET /items/:id` attaches
 * `discounted_price` from the calling buyer's own negotiated price, and the
 * chat SSE `data-discount` frame patches the same entry. Nothing emptied it
 * when the session changed, so A negotiates an item down, signs out, B signs in
 * on the same tab, and `fetchIfMissing` hands B the price A negotiated.
 *
 * Driven off the session ref rather than its own listener: `useAuth` holds the
 * single copy of who is signed in, and every transition (including the null on
 * sign-out) is written there, so watching it is the same signal with nothing
 * extra to leak.
 *
 * The immediate run primes the owner from the identity `plugins/auth.client.ts`
 * restored: that plugin is `enforce: 'pre'` and awaits `/auth/session`, so by
 * the time this runs the signed-in user is already known and no page can have
 * fetched under the wrong owner.
 */
import { useItemStore } from '~/stores/item'
import { resolveUserId } from '~/utils/auth'

export default defineNuxtPlugin(() => {
  const { user } = useAuth()
  const store = useItemStore()

  watch(
    () => resolveUserId(user.value),
    userId => store.setOwner(userId ?? null),
    { immediate: true }
  )
})
