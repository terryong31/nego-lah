import * as Sentry from '@sentry/nuxt'
import { useRuntimeConfig } from '#imports'

const config = useRuntimeConfig()

const isProd = process.env.NODE_ENV === 'production'
if (!import.meta.test && isProd) {
  // When autoInjectServerSentry is 'top-level-import', this file may be evaluated
  // before Nuxt applies its .env overrides to useRuntimeConfig().
  const dsn = process.env.NUXT_PUBLIC_SENTRY_DSN || config?.public?.sentryDsn
  if (!dsn) {
    throw new Error('SENTRY_DSN must be configured in production')
  }

  Sentry.init({
    dsn: dsn,
    environment: 'production',
    release: process.env.SENTRY_RELEASE || 'latest',
    // Mirrors the backend's Sentry config (see backend/main.py).
    sendDefaultPii: true,
    enableLogs: true,
    tracesSampleRate: 0.2
  })
}
