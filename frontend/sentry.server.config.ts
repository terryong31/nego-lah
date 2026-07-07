import * as Sentry from '@sentry/nuxt'
import { useRuntimeConfig } from '#imports'

const config = useRuntimeConfig()

// When autoInjectServerSentry is 'top-level-import', this file may be evaluated
// before Nuxt applies its .env overrides to useRuntimeConfig().
const dsn = process.env.NUXT_PUBLIC_SENTRY_DSN || config.public.sentryDsn

if (dsn) {
  Sentry.init({
    dsn: dsn,
    environment: process.env.NODE_ENV === 'production' ? 'production' : 'development',
    // Mirrors the backend's Sentry config (see backend/main.py).
    sendDefaultPii: true,
    enableLogs: true,
    tracesSampleRate: 1.0
  })
}
