// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  modules: [
    '@nuxt/eslint',
    '@nuxt/ui',
    '@nuxtjs/supabase'
  ],

  devtools: {
    enabled: true
  },

  css: ['~/assets/css/main.css'],

  runtimeConfig: {
    public: {
      apiBaseUrl: process.env.API_BASE_URL || 'http://localhost:8000'
    }
  },

  // The admin console authenticates via an httpOnly cookie on the API host, which
  // SSR can't forward — render it client-side only (no SEO needed there anyway).
  routeRules: {
    '/_console/**': { ssr: false },
    '/_console': { ssr: false }
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
    localApiEndpoint: '/_nuxt_icon'
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
