import * as Sentry from '@sentry/nuxt'
import { useRuntimeConfig } from '#imports'

const config = useRuntimeConfig()

if (config.public.sentryDsn) {
  Sentry.init({
    dsn: config.public.sentryDsn,
    environment: process.env.NODE_ENV === 'production' ? 'production' : 'development',
    // Mirrors the backend's Sentry config (see backend/main.py).
    sendDefaultPii: true,
    enableLogs: true,
    tracesSampleRate: 1.0
  })
}
