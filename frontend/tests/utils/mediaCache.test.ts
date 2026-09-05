import { describe, expect, it, vi } from 'vitest'
import {
  MEDIA_PURGE_FLAG,
  isCachedMediaUrl,
  purgeCachedMedia,
  purgeCachedMediaOnce
} from '~/utils/mediaCache'

/**
 * SPEC-030 — the old catch-all storage route could leave a dead ~13.5 MB video
 * in Cache Storage. Nothing serves it any more, but it holds quota until the
 * browser evicts it, so the page cleans it out once.
 */

const CDN = 'https://umtsegjkgpfefjvhyysh.supabase.co/storage/v1/object/public/images'

/** Minimal stand-in for the slice of CacheStorage the purge actually touches. */
function fakeCacheStorage(contents: Record<string, string[]>) {
  const state = new Map(Object.entries(contents).map(([name, urls]) => [name, [...urls]]))

  const open = vi.fn(async (name: string) => ({
    keys: async () => (state.get(name) ?? []).map(url => ({ url })),
    delete: async (request: { url: string }) => {
      const urls = state.get(name)
      if (!urls) return false
      const index = urls.indexOf(request.url)
      if (index === -1) return false
      urls.splice(index, 1)
      return true
    }
  }))

  return {
    storage: { keys: async () => [...state.keys()], open } as unknown as CacheStorage,
    remaining: () => Object.fromEntries(state)
  }
}

describe('utils/mediaCache', () => {
  describe('isCachedMediaUrl', () => {
    it('flags streaming media on any origin, query strings included', () => {
      expect(isCachedMediaUrl(`${CDN}/videos/negotiation-demo.mp4`)).toBe(true)
      expect(isCachedMediaUrl('https://negolah.my/videos/negotiation-demo.mp4')).toBe(true)
      expect(isCachedMediaUrl(`${CDN}/videos/demo.webm?v=2`)).toBe(true)
      expect(isCachedMediaUrl(`${CDN}/audio/chime.mp3`)).toBe(true)
    })

    it('spares everything the service worker is still allowed to cache', () => {
      expect(isCachedMediaUrl(`${CDN}/branding/logo.png`)).toBe(false)
      expect(isCachedMediaUrl('https://negolah.my/_nuxt/entry.js')).toBe(false)
      expect(isCachedMediaUrl('https://api.negolah.my/api/items')).toBe(false)
      // A path segment that merely contains "mp4" is not a media file.
      expect(isCachedMediaUrl('https://negolah.my/mp4/guide.html')).toBe(false)
    })

    it('does not throw on a malformed URL', () => {
      expect(isCachedMediaUrl('not a url')).toBe(false)
    })
  })

  describe('purgeCachedMedia', () => {
    it('deletes media from every cache while leaving other entries intact', async () => {
      const { storage, remaining } = fakeCacheStorage({
        'supabase-storage-images': [
          `${CDN}/videos/negotiation-demo.mp4`,
          `${CDN}/branding/logo.png`
        ],
        'static-images': [`${CDN}/listings/item-1.webp`],
        'workbox-precache-v2': ['https://negolah.my/videos/negotiation-demo.mp4']
      })

      const purged = await purgeCachedMedia(storage)

      expect(purged).toBe(2)
      expect(remaining()).toEqual({
        'supabase-storage-images': [`${CDN}/branding/logo.png`],
        'static-images': [`${CDN}/listings/item-1.webp`],
        'workbox-precache-v2': []
      })
    })

    it('is a no-op when nothing media-shaped is cached', async () => {
      const { storage } = fakeCacheStorage({ 'static-images': [`${CDN}/branding/logo.png`] })
      await expect(purgeCachedMedia(storage)).resolves.toBe(0)
    })
  })

  describe('purgeCachedMediaOnce', () => {
    function fakeStorage(initial: Record<string, string> = {}) {
      const map = new Map(Object.entries(initial))
      return {
        getItem: (key: string) => map.get(key) ?? null,
        setItem: (key: string, value: string) => void map.set(key, value),
        snapshot: () => Object.fromEntries(map)
      }
    }

    it('purges once and records a flag so later visits cost nothing', async () => {
      const { storage: cacheStorage, remaining } = fakeCacheStorage({
        'supabase-storage-images': [`${CDN}/videos/negotiation-demo.mp4`]
      })
      const local = fakeStorage()

      await expect(purgeCachedMediaOnce(cacheStorage, local)).resolves.toBe(1)
      expect(local.snapshot()[MEDIA_PURGE_FLAG]).toBe('true')
      expect(remaining()['supabase-storage-images']).toEqual([])

      // Second visit: the flag short-circuits before touching Cache Storage.
      const openSpy = cacheStorage.open as unknown as ReturnType<typeof vi.fn>
      openSpy.mockClear()
      await expect(purgeCachedMediaOnce(cacheStorage, local)).resolves.toBe(0)
      expect(openSpy).not.toHaveBeenCalled()
    })

    it('stays inert when Cache Storage is unavailable', async () => {
      await expect(purgeCachedMediaOnce(undefined, fakeStorage())).resolves.toBe(0)
    })

    it('still purges when localStorage throws, without surfacing the error', async () => {
      const { storage: cacheStorage } = fakeCacheStorage({
        'static-images': [`${CDN}/videos/demo.mp4`]
      })
      const hostile = {
        getItem: () => { throw new Error('denied') },
        setItem: () => { throw new Error('denied') }
      }

      await expect(purgeCachedMediaOnce(cacheStorage, hostile)).resolves.toBe(0)
    })
  })
})
