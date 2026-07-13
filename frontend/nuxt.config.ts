// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  modules: [
    '@nuxt/eslint',
    '@nuxt/ui',
    '@nuxtjs/supabase',
    '@nuxtjs/mdc',
    '@sentry/nuxt/module'
  ],

  devtools: {
    enabled: true
  },

  css: ['~/assets/css/main.css'],

  runtimeConfig: {
    public: {
      apiBaseUrl: process.env.API_BASE_URL || 'http://localhost:8000',
      // Not secret (it's shipped to every browser anyway) — safe to leave empty
      // by default. Set NUXT_PUBLIC_SENTRY_DSN (or SENTRY_DSN at build time) to enable.
      sentryDsn: process.env.SENTRY_DSN || ''
    }
  },

  // The admin console authenticates via an httpOnly cookie on the API host, which
  // SSR can't forward — render it client-side only (no SEO needed there anyway).
  routeRules: {
    '/_console/**': { ssr: false },
    '/_console': { ssr: false }
  },

  // Nuxt disables client source maps by default. "hidden" generates them (so
  // Sentry can upload readable stack traces) without adding a `sourceMappingURL`
  // comment to the shipped JS — the .map files are then deleted post-upload
  // (see the `sentry.sourcemaps` option below) so they're never served publicly.
  sourcemap: {
    client: 'hidden'
  },

  compatibilityDate: '2025-01-15',

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  },

  // @nuxt/icon serves its local collections from `localApiEndpoint`, which
  // defaults to `/api/_nuxt_icon`. In production Caddy routes ALL `/api/*` to
  // the FastAPI backend, which would hijack that route and 404 every icon.
  // Move it off `/api` so it stays on the Nuxt server.
  icon: {
    localApiEndpoint: '/_nuxt_icon',
    // Pre-bundle the icons actually used in the app (static analysis of literal
    // `i-*` names) into the client build, so they render instantly and offline
    // with no runtime request to the Iconify API. This also removes the
    // "failed to load icon" noise and per-icon network timeouts in CI/tests,
    // where there's no network to api.iconify.design.
    clientBundle: {
      scan: true,
      sizeLimitKb: 512
    }
  },

  // The production image runs `node .output/server/index.mjs` directly (no
  // `--import` flag available), so server-side Sentry needs the top-level-import
  // auto-injection mode to instrument Nitro.
  //
  // org/project/authToken are read from SENTRY_ORG / SENTRY_PROJECT /
  // SENTRY_AUTH_TOKEN, set only at Docker build time (see frontend/Dockerfile
  // and .github/workflows/deploy.yml) — never present in the runtime container.
  // Source map upload is skipped automatically whenever authToken is unset
  // (e.g. local dev builds), so nothing breaks without it.
  sentry: {
    autoInjectServerSentry: 'top-level-import',
    org: process.env.SENTRY_ORG,
    project: process.env.SENTRY_PROJECT,
    authToken: process.env.SENTRY_AUTH_TOKEN,
    // Maps are uploaded to Sentry, then deleted locally so the shipped image
    // never carries readable, unminified source.
    sourcemaps: {
      filesToDeleteAfterUpload: ['.output/**/*.map']
    }
  },

  supabase: {
    // SSR mode — session is handled server-side via cookies
    redirectOptions: {
      login: '/login',
      callback: '/confirm',
      // Public routes that don't require auth.
      // /_console is the admin area; it has its OWN cookie-based auth (handled by
      // the backend), so it must be excluded from the Supabase-user redirect.
      exclude: ['/', '/items', '/items/*', '/login', '/register', '/forgot-password', '/reset-password', '/privacy', '/terms', '/_console', '/_console/*']
    }
  }
})
