/**
 * SPEC-030: clears media left in Cache Storage by the old catch-all Supabase
 * storage route. Deferred to idle — it is pure housekeeping and must never
 * compete with the first paint or the video it exists to unblock.
 */
export default defineNuxtPlugin(() => {
  if (typeof caches === 'undefined') return

  onNuxtReady(() => {
    void purgeCachedMediaOnce(caches, window.localStorage)
  })
})
