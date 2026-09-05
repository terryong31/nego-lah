/**
 * Workbox runtime caching rules for the service worker (SPEC-030).
 *
 * Extracted out of `nuxt.config.ts` so the patterns can be unit-tested against
 * real URLs — see `tests/pwa-runtime-caching.test.ts`. The bug this guards
 * against was a pattern that quietly matched more URLs than intended.
 *
 * THE MEDIA RULE: no route may match audio or video. Workbox's
 * `StaleWhileRevalidate` calls `response.clone()` so it can cache the body,
 * which tees the stream. A media element only reads as far as its buffer, so
 * the tee'd branch stalls under backpressure and playback can deadlock before
 * the first frame ever decodes — intermittently, depending on network timing.
 * `cacheableResponse` rejects the `206` byte-range replies only *after* the
 * clone, so a media route pays that cost for no cache benefit at all. Leaving
 * media unmatched means Workbox never calls `respondWith` and the browser owns
 * the stream end to end, byte-range support intact.
 */

/** Extensions that must never be routed through the service worker. */
export const MEDIA_EXTENSIONS = [
  'mp4',
  'webm',
  'ogg',
  'ogv',
  'mov',
  'm4v',
  'mp3',
  'wav',
  'm4a'
] as const

/** Extensions that are safe to cache — none of them stream. */
const IMAGE_EXTENSION_PATTERN = '(?:png|jpe?g|svg|gif|webp|avif)'

/** Optional query string, so `?width=400` style transforms still match. */
const OPTIONAL_QUERY = '(?:\\?.*)?$'

export interface RuntimeCachingRule {
  urlPattern: RegExp
  handler: 'CacheFirst' | 'NetworkFirst' | 'NetworkOnly' | 'StaleWhileRevalidate'
  options?: {
    cacheName?: string
    expiration?: {
      maxEntries?: number
      maxAgeSeconds?: number
    }
    cacheableResponse?: {
      statuses: number[]
    }
  }
}

/**
 * Order matters: Workbox registers these as routes and the first match wins.
 */
export const runtimeCaching: RuntimeCachingRule[] = [
  {
    urlPattern: /^https:\/\/fonts\.(?:googleapis|gstatic)\.com\/.*/i,
    handler: 'CacheFirst',
    options: {
      cacheName: 'google-fonts',
      expiration: {
        maxEntries: 10,
        maxAgeSeconds: 60 * 60 * 24 * 365
      },
      cacheableResponse: {
        statuses: [0, 200]
      }
    }
  },
  {
    urlPattern: new RegExp(`\\.${IMAGE_EXTENSION_PATTERN}${OPTIONAL_QUERY}`, 'i'),
    handler: 'StaleWhileRevalidate',
    options: {
      cacheName: 'static-images',
      expiration: {
        maxEntries: 100,
        maxAgeSeconds: 60 * 60 * 24 * 30
      },
      cacheableResponse: {
        statuses: [0, 200]
      }
    }
  },
  {
    // Public Supabase Storage objects — images only. The previous
    // `/storage/v1/object/public/.*` catch-all also matched
    // `videos/negotiation-demo.mp4`, which is what broke the homepage video.
    urlPattern: new RegExp(
      `/storage/v1/object/public/.*\\.${IMAGE_EXTENSION_PATTERN}${OPTIONAL_QUERY}`,
      'i'
    ),
    handler: 'StaleWhileRevalidate',
    options: {
      cacheName: 'supabase-storage-images',
      expiration: {
        maxEntries: 100,
        maxAgeSeconds: 60 * 60 * 24 * 7
      },
      cacheableResponse: {
        statuses: [0, 200]
      }
    }
  },
  {
    // Never serve stale responses for API calls or chat / negotiation
    urlPattern: /^https:\/\/api\.negolah\.my\/api\/.*/i,
    handler: 'NetworkOnly'
  }
]
