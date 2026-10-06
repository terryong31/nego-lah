/**
 * The one Content-Security-Policy (audit SEC-4).
 *
 * It used to be written out twice — `public/_headers`, which is what
 * Cloudflare Pages actually serves, and `routeRules` in nuxt.config, which only
 * the dev server and `nuxt preview` see — and the two had already drifted:
 * production still allowed `*.supabase.co`, which SPEC-093/094 removed from the
 * browser, and both shipped the localhost API origins.
 *
 * `public/_headers` cannot import this (it is a static file), so
 * tests/security-headers.test.ts asserts it carries exactly
 * `contentSecurityPolicy({ dev: false })`.
 */
const DEV_API_ORIGINS = ['http://localhost:8000', 'http://127.0.0.1:8000']

export function contentSecurityPolicy({ dev }: { dev: boolean }): string {
  const connect = [
    '\'self\'',
    'https://api.negolah.my',
    ...(dev ? DEV_API_ORIGINS : []),
    'https://*.sentry.io',
    'https://challenges.cloudflare.com',
    'https://cloudflareinsights.com',
    'https://*.google-analytics.com',
    'https://*.analytics.google.com',
    'https://*.googletagmanager.com'
  ]
  return [
    'default-src \'self\'',
    'script-src \'self\' \'unsafe-inline\' \'unsafe-eval\' https://challenges.cloudflare.com https://static.cloudflareinsights.com https://www.googletagmanager.com https://*.google-analytics.com',
    'worker-src \'self\' blob:',
    'child-src \'self\' blob:',
    'style-src \'self\' \'unsafe-inline\' https://fonts.googleapis.com',
    'font-src \'self\' data: https://fonts.gstatic.com',
    'img-src \'self\' data: blob: https:',
    'media-src \'self\' https: blob:',
    `connect-src ${connect.join(' ')}`,
    'frame-src \'self\' https://challenges.cloudflare.com https://js.stripe.com',
    'object-src \'none\'',
    'base-uri \'self\''
  ].join('; ') + ';'
}
