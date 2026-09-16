/**
 * SPEC-082: keep the item store scoped to the buyer who is actually signed in.
 *
 * `useItemStore` caches user-scoped rows — `GET /items/:id` attaches
 * `discounted_price` from the calling buyer's own negotiated price, and the
 * chat SSE `data-discount` frame patches the same entry. Nothing emptied it
 * when the session changed, so A negotiates an item down, signs out, B signs in
 * on the same tab, and `fetchIfMissing` hands B the price A negotiated.
 *
 * Driven off `useSupabaseUser()` rather than a second
 * `supabase.auth.onAuthStateChange` listener: the module's own plugin already
 * owns that subscription and writes every transition (including the null on
 * sign-out) into this ref, so watching it is the same signal with no extra
 * listener to leak — and nothing here depends on the client's shape.
 *
 * The immediate run primes the owner from the identity that plugin restored:
 * it is `enforce: 'pre'` and awaits `getSession()` + `getClaims()`, so by the
 * time this runs the signed-in user is already known and no page can have
 * fetched under the wrong owner.
 */
import { useItemStore } from '~/stores/item'
import { resolveUserId } from '~/utils/auth'

export default defineNuxtPlugin(() => {
  const user = useSupabaseUser()
  const store = useItemStore()

  // The ref holds the JWT claims, where the user id is `sub`; `id` is the
  // spelling the rest of the app reads off it, so accept either rather than
  // silently resolving to null and never clearing anything.
  watch(
    () => resolveUserId(user.value),
    userId => store.setOwner(userId ?? null),
    { immediate: true }
  )
})
