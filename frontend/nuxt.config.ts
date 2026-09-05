import { runtimeCaching } from './pwa/runtime-caching'

export default defineNuxtConfig({

  modules: [
    '@nuxt/eslint',
    '@nuxt/ui',
    '@nuxtjs/supabase',
    '@nuxtjs/mdc',
    '@nuxtjs/turnstile',
    '@nuxtjs/i18n',
    '@sentry/nuxt/module',
    '@vite-pwa/nuxt'
  ],
  ssr: false,

  devtools: {
    enabled: true
  },

  app: {
    head: {
      title: 'Nego-Lah',
      htmlAttrs: {
        lang: 'en'
      },
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, maximum-scale=5' },
        { name: 'description', content: 'Malaysia\'s autonomous second-hand marketplace with AI price negotiations. Buy and sell pre-loved gadgets, fashion, and collectibles at fair market prices.' },
        { name: 'keywords', content: 'second-hand marketplace, AI negotiation, nego-lah, pre-loved items, Malaysia marketplace, automated bargaining' },
        { name: 'theme-color', content: '#10b981', media: '(prefers-color-scheme: light)' },
        { name: 'theme-color', content: '#09090b', media: '(prefers-color-scheme: dark)' },
        // OpenGraph
        { property: 'og:type', content: 'website' },
        { property: 'og:site_name', content: 'Nego-Lah' },
        { property: 'og:title', content: 'Nego-Lah · Autonomous AI Price Negotiation Marketplace' },
        { property: 'og:description', content: 'Malaysia\'s autonomous second-hand marketplace with AI price negotiations. Buy and sell pre-loved items at fair market prices.' },
        { property: 'og:image', content: 'https://negolah.my/og-image.png' },
        { property: 'og:image:width', content: '1200' },
        { property: 'og:image:height', content: '675' },
        { property: 'og:image:alt', content: 'Nego-Lah - Autonomous AI Price Negotiation Marketplace' },
        { property: 'og:url', content: 'https://negolah.my' },
        // Twitter Cards
        { name: 'twitter:card', content: 'summary_large_image' },
        { name: 'twitter:site', content: '@negolah' },
        { name: 'twitter:title', content: 'Nego-Lah · Autonomous AI Price Negotiation Marketplace' },
        { name: 'twitter:description', content: 'Malaysia\'s autonomous second-hand marketplace with AI price negotiations. Buy and sell pre-loved items at fair market prices.' },
        { name: 'twitter:image', content: 'https://negolah.my/og-image.png' },
        { name: 'twitter:image:alt', content: 'Nego-Lah - Autonomous AI Price Negotiation Marketplace' }
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'apple-touch-icon', sizes: '180x180', href: '/apple-touch-icon.png' },
        { rel: 'canonical', href: 'https://negolah.my' }
      ]
    }
  },

  css: ['~/assets/css/main.css'],
  spaLoadingTemplate: 'spa-loading-template.html',

  runtimeConfig: {
    public: {
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL || (process.env.NODE_ENV === 'production' ? 'https://api.negolah.my' : 'http://localhost:8000'),
      sentryDsn: process.env.NUXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN || 'https://7c4d1217c773d186925bc7c19e6d0368@o4511643096907776.ingest.us.sentry.io/4511683725361152',
      turnstileEnabled: process.env.NODE_ENV === 'production' || process.env.NUXT_PUBLIC_TURNSTILE_ENABLED === 'true',
      turnstileSiteKey: process.env.NODE_ENV === 'production' ? (process.env.NUXT_PUBLIC_TURNSTILE_SITE_KEY || '0x4AAAAAAEmNZSy3jXy_Eh38') : '',
      gtmId: process.env.NUXT_PUBLIC_GTM_ID || '',
      gaId: process.env.NUXT_PUBLIC_GA_ID || 'G-M4J8K55PPM'
    }
  },

  // The catch-all '/**' rule adds security headers that mirror production (Caddy / Cloudflare Pages).
  // Includes full CSP and Service Worker directives.
  routeRules: {
    '/**': {
      headers: {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        'Content-Security-Policy': 'default-src \'self\'; script-src \'self\' \'unsafe-inline\' \'unsafe-eval\' https://challenges.cloudflare.com https://static.cloudflareinsights.com https://www.googletagmanager.com https://*.google-analytics.com; worker-src \'self\' blob:; child-src \'self\' blob:; style-src \'self\' \'unsafe-inline\' https://fonts.googleapis.com; font-src \'self\' data: https://fonts.gstatic.com; img-src \'self\' data: blob: https:; media-src \'self\' https: blob:; connect-src \'self\' https://api.negolah.my http://localhost:8000 http://127.0.0.1:8000 https://*.supabase.co wss://*.supabase.co https://*.sentry.io https://challenges.cloudflare.com https://cloudflareinsights.com https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com; frame-src \'self\' https://challenges.cloudflare.com https://js.stripe.com; object-src \'none\'; base-uri \'self\';'
      }
    }
  },

  // Nuxt disables client source maps by default. "hidden" generates them (so
  // Sentry can upload readable stack traces) without adding a `sourceMappingURL`
  // comment to the shipped JS — the .map files are then deleted post-upload
  // (see the `sentry.sourcemaps` option below) so they're never served publicly.
  sourcemap: {
    client: 'hidden'
  },

  compatibilityDate: '2025-01-15',

  nitro: {
    prerender: {
      routes: ['/']
    }
  },

  vite: {
    optimizeDeps: {
      include: [
        '@vue/devtools-core',
        '@vue/devtools-kit'
      ]
    }
  },

  typescript: {
    shim: true
  },

  hooks: {
    'components:extend'(components) {
      const pageHero = components.find(c => c.pascalName === 'UPageHero')
      if (pageHero) {
        components.push({
          ...pageHero,
          pascalName: 'UHero',
          kebabName: 'u-hero'
        })
      }
      const pageSection = components.find(c => c.pascalName === 'UPageSection')
      if (pageSection) {
        components.push({
          ...pageSection,
          pascalName: 'USection',
          kebabName: 'u-section'
        })
      }
    }
  },

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  },

  i18n: {
    strategy: 'no_prefix',
    defaultLocale: 'en',
    locales: [
      { code: 'en', language: 'en-US', name: 'English' },
      { code: 'ms', language: 'ms-MY', name: 'Bahasa Melayu' },
      { code: 'zh', language: 'zh-CN', name: '简体中文' }
    ],
    detectBrowserLanguage: false,
    vueI18n: './i18n.config.ts'
  },

  // @nuxt/icon serves its local collections from `localApiEndpoint`, which
  // defaults to `/api/_nuxt_icon`. In production Caddy routes ALL `/api/*` to
  // the FastAPI backend, which would hijack that route and 404 every icon.
  // Move it off `/api` so it stays on the Nuxt server.
  icon: {
    localApiEndpoint: '/_nuxt_icon',
    // The brand mark, served as a normal `i-nego-mark` icon name so it can be
    // passed to any Nuxt UI component's `icon` prop (see the chat indicator in
    // pages/chat.vue) instead of hand-rolling an SVG into a component slot.
    // The file is monochrome `currentColor`, so `text-*` utilities theme it.
    customCollections: [
      { prefix: 'nego', dir: './app/assets/icons' }
    ],
    // Pre-bundle the icons actually used in the app (static analysis of literal
    // `i-*` names) into the client build, so they render instantly and offline
    // with no runtime request to the Iconify API. This also removes the
    // "failed to load icon" noise and per-icon network timeouts in CI/tests,
    // where there's no network to api.iconify.design.
    clientBundle: {
      scan: true,
      // `scan` only sees the app's own source, so icons injected by Nuxt UI
      // internals (the loading spinner, chevrons, close, etc. — all living in
      // node_modules) are missed and then fail to render wherever there's no
      // icon server: SSR and, especially, the Vitest env (the `loader-circle`
      // spinner alone logged ~2.4k "failed to load icon" lines in CI). List
      // Nuxt UI's default icon set explicitly so those are bundled too.
      icons: [
        'lucide:loader-circle',
        'lucide:check',
        'lucide:x',
        'lucide:chevron-down',
        'lucide:chevron-up',
        'lucide:chevron-left',
        'lucide:chevron-right',
        'lucide:chevrons-left',
        'lucide:chevrons-right',
        'lucide:arrow-left',
        'lucide:arrow-right',
        'lucide:arrow-up-right',
        'lucide:ellipsis',
        'lucide:search',
        'lucide:plus',
        'lucide:minus',
        'lucide:folder',
        'lucide:folder-open'
      ],
      sizeLimitKb: 512,
      // ssr: false — the generated site has no icon server to hit at runtime,
      // so custom collections must be inlined into the client bundle too.
      includeCustomCollections: true
    }
  },

  pwa: {
    registerType: 'autoUpdate',
    manifest: {
      name: 'Nego-Lah · Autonomous AI Price Negotiation Marketplace',
      short_name: 'Nego-Lah',
      description: 'Malaysia\'s premier second-hand marketplace with autonomous AI price negotiations.',
      theme_color: '#10b981',
      background_color: '#ffffff',
      display: 'standalone',
      orientation: 'portrait-primary',
      scope: '/',
      start_url: '/',
      icons: [
        {
          src: '/favicon.svg',
          sizes: 'any',
          type: 'image/svg+xml',
          purpose: 'any'
        },
        {
          src: '/apple-touch-icon.png',
          sizes: '180x180',
          type: 'image/png'
        },
        {
          src: '/icon-192.png',
          sizes: '192x192',
          type: 'image/png',
          purpose: 'any maskable'
        },
        {
          src: '/icon-512.png',
          sizes: '512x512',
          type: 'image/png',
          purpose: 'any maskable'
        }
      ]
    },
    workbox: {
      navigateFallback: '/',
      navigateFallbackDenylist: [/^\/api\//, /^\/_console/],
      globPatterns: ['**/*.{js,css,html,svg,png,ico,woff,woff2}'],
      cleanupOutdatedCaches: true,
      clientsClaim: true,
      skipWaiting: true,
      // SPEC-030: media must never be routed through the service worker —
      // see pwa/runtime-caching.ts for why. Kept in a separate module so the
      // URL patterns can be unit-tested against real URLs.
      runtimeCaching
    },
    client: {
      // SPEC-030: `useRegisterSW` only looks for a new service worker on a hard
      // navigation, and this is an SPA (ssr: false) — client-side routing makes
      // none. Without this poll, a tab left open keeps running whichever worker
      // it booted with, so a shipped fix never reaches it. Re-checks hourly;
      // `registerType: 'autoUpdate'` plus skipWaiting/clientsClaim then
      // activates the replacement and claims open clients immediately.
      periodicSyncForUpdates: 3600,
      // SPEC-030: when enabled, @vite-pwa/nuxt calls preventDefault() on
      // `beforeinstallprompt` and stashes the event for a custom prompt. No
      // component ever calls `$pwa.install()`, so Chrome suppressed its own
      // banner and logged "Banner not shown: beforeinstallpromptevent
      // .preventDefault() called." Leave installation to the browser's native
      // affordance instead.
      installPrompt: false
    },
    devOptions: {
      enabled: false,
      suppressWarnings: true,
      type: 'module'
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
    enabled: process.env.NODE_ENV === 'production',
    org: process.env.SENTRY_ORG || process.env.NUXT_PUBLIC_SENTRY_ORG || 'nego-lah',
    project: process.env.SENTRY_PROJECT || process.env.NUXT_PUBLIC_SENTRY_PROJECT || 'nego-lah-frontend',
    authToken: process.env.SENTRY_AUTH_TOKEN,
    release: {
      name: process.env.SENTRY_RELEASE || 'latest'
    },
    sourcemaps: {
      filesToDeleteAfterUpload: ['.output/**/*.map']
    }
  },

  supabase: {
    url: process.env.NUXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL,
    key: process.env.NUXT_PUBLIC_SUPABASE_KEY || process.env.SUPABASE_KEY,
    cookieOptions: {
      secure: process.env.NODE_ENV === 'production'
    },
    redirectOptions: {
      login: '/login',
      callback: '/confirm',
      // This module's guard runs before any page middleware, so on a lapsed
      // session it — not our own `auth` middleware — is what redirects, and it
      // has no way to attach a `?redirect=` query. Letting it stash the blocked
      // page in a cookie is the module's own answer to that; `pages/login.vue`
      // plucks it so the visitor lands back where they were kicked off.
      saveRedirectToCookie: true,
      // Public routes that don't require auth.
      // /_console is the admin area; it has its OWN cookie-based auth (handled by
      // the backend), so it must be excluded from the Supabase-user redirect.
      exclude: ['/', '/items', '/items/*', '/login', '/register', '/forgot-password', '/reset-password', '/privacy', '/terms', '/_console', '/_console/*']
    }
  },

  turnstile: {
    siteKey: process.env.NODE_ENV === 'production' ? (process.env.NUXT_PUBLIC_TURNSTILE_SITE_KEY || '0x4AAAAAAEmNZSy3jXy_Eh38') : ''
  }
})
