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
    tracesSampleRate: 1.0,
    integrations: [
      Sentry.replayIntegration({
        maskAllText: false, // Turn off masking so you can actually see the replay content
        blockAllMedia: false
      })
    ],
    // Bumped to 1.0 for testing so EVERY session is recorded.
    // You can lower this back to 0.1 once you verify replays are showing.
    replaysSessionSampleRate: 1.0,
    replaysOnErrorSampleRate: 1.0
  })
}
