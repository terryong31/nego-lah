import { MEDIA_EXTENSIONS } from '~~/pwa/runtime-caching'

/**
 * One-shot Cache Storage cleanup (SPEC-030).
 *
 * Until the runtime caching rules were narrowed, a catch-all
 * `/storage/v1/object/public/.*` route ran the 13.5 MB product demo video
 * through `StaleWhileRevalidate`. No route matches media any more, so anything
 * that route managed to store is now unreachable — but `cleanupOutdatedCaches`
 * only prunes stale *precaches*, so it lingers and holds storage quota until
 * the browser evicts it. Cache Storage is same-origin accessible from the page,
 * so the cleanup runs here rather than dragging the whole build over to
 * `injectManifest` for one deletion.
 */

/** Bump the suffix to re-run the purge for everyone. */
export const MEDIA_PURGE_FLAG = 'negolah:media-cache-purged:v1'

const MEDIA_PATHNAME_PATTERN = new RegExp(`\\.(?:${MEDIA_EXTENSIONS.join('|')})$`, 'i')

/** Cache keys are absolute URLs; only the pathname decides, so `?v=2` is fine. */
export function isCachedMediaUrl(url: string): boolean {
  try {
    return MEDIA_PATHNAME_PATTERN.test(new URL(url).pathname)
  } catch {
    return false
  }
}

/** Deletes every media entry across all caches. Returns how many were removed. */
export async function purgeCachedMedia(cacheStorage: CacheStorage): Promise<number> {
  let purged = 0

  for (const name of await cacheStorage.keys()) {
    const cache = await cacheStorage.open(name)
    for (const request of await cache.keys()) {
      if (!isCachedMediaUrl(request.url)) continue
      if (await cache.delete(request)) purged++
    }
  }

  return purged
}

type FlagStorage = Pick<Storage, 'getItem' | 'setItem'>

/**
 * Runs {@link purgeCachedMedia} at most once per browser. Never throws: this is
 * housekeeping, and Cache Storage or `localStorage` can both be unavailable
 * (private windows, blocked site data) with nothing useful to do about it.
 */
export async function purgeCachedMediaOnce(
  cacheStorage: CacheStorage | undefined,
  storage: FlagStorage | undefined
): Promise<number> {
  if (!cacheStorage) return 0

  try {
    if (storage?.getItem(MEDIA_PURGE_FLAG) === 'true') return 0

    const purged = await purgeCachedMedia(cacheStorage)
    storage?.setItem(MEDIA_PURGE_FLAG, 'true')
    return purged
  } catch {
    return 0
  }
}
