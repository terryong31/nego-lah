import * as Sentry from '@sentry/nuxt'
import { useRuntimeConfig } from '#imports'

// Skip Sentry initialization during unit tests and in development mode (strictly enforced in production)
const isProd = process.env.NODE_ENV === 'production'
if (!import.meta.test && isProd) {
  const config = useRuntimeConfig()
  const dsn = config?.public?.sentryDsn
    || process.env.NUXT_PUBLIC_SENTRY_DSN
    || 'https://7c4d1217c773d186925bc7c19e6d0368@o4511643096907776.ingest.us.sentry.io/4511683725361152'

  if (!dsn) {
    throw new Error('SENTRY_DSN must be configured in production')
  }

  const integrations = []

  if (typeof Sentry.replayIntegration === 'function') {
    integrations.push(
      Sentry.replayIntegration({
        // Privacy & Compliance: Mask sensitive content in production
        maskAllText: isProd,
        blockAllMedia: isProd,
        maskAllInputs: true,
        networkDetailAllowUrls: [
          typeof window !== 'undefined' ? window.location.origin : '',
          'http://localhost:8000',
          'http://127.0.0.1:8000',
          'https://api.negolah.my'
        ].filter(Boolean),
        networkCaptureBodies: true,
        networkRequestHeaders: ['X-CSRF-Token', 'X-Turnstile-Token', 'sentry-trace', 'baggage'],
        networkResponseHeaders: ['content-type', 'sentry-trace', 'baggage'],
        // Only replay very serious errors (fatal crashes, unhandled exceptions, and 5xx server failures)
        beforeErrorSampling: (event) => {
          // 1. Explicit fatal errors
          if (event.level === 'fatal') return true

          // 2. Unhandled exceptions (crashes that were uncaught by client code)
          const isUnhandled = event.exception?.values?.some(
            val => val.mechanism?.handled === false
          )
          if (isUnhandled) return true

          // 3. Severe backend 5xx failures captured in contexts/tags
          const statusCode = Number(
            event.tags?.statusCode
            || event.contexts?.response?.status_code
            || event.extra?.status_code
            || 0
          )
          if (statusCode >= 500) return true

          // Drop replays for handled user validation, 4xx, network aborts, or warnings
          return false
        }
      })
    )
  }

  Sentry.init({
    dsn,
    environment: isProd ? 'production' : 'development',
    release: process.env.SENTRY_RELEASE || '731092f67e3a1eefb8716bc53dc145016e6c412f',
    sendDefaultPii: true,
    enableLogs: true,
    // Traces: 20% in production to conserve quota, 100% in development
    tracesSampleRate: isProd ? 0.2 : 1.0,
    tracePropagationTargets: [
      'localhost',
      '127.0.0.1',
      'api.negolah.my',
      /^https:\/\/api\.negolah\.my/,
      /^http:\/\/localhost:8000/,
      /^http:\/\/127\.0\.0\.1:8000/
    ],
    integrations: [
      ...integrations,
      // Only capture console.error (never warn, which floods Sentry with Vue/i18n warnings)
      Sentry.captureConsoleIntegration({ levels: ['error'] })
    ],
    // Filter out noisy, benign browser errors and cancellation events
    beforeSend: (event, hint) => {
      const error = hint?.originalException
      const errorMessage = typeof error === 'string'
        ? error
        : (error instanceof Error ? error.message : event.message || '')

      if (
        errorMessage.includes('ResizeObserver loop')
        || errorMessage.includes('ResizeObserver loop completed with undelivered notifications')
        || errorMessage.includes('AbortError')
        || errorMessage.includes('Extension context invalidated')
        || (errorMessage.includes('Failed to fetch') && typeof navigator !== 'undefined' && !navigator.onLine)
      ) {
        return null
      }

      return event
    },
    // Session Replay rates:
    // replaysSessionSampleRate: 0.0 (Do NOT record normal healthy sessions; zero quota waste)
    replaysSessionSampleRate: 0.0,
    // replaysOnErrorSampleRate: 1.0 in production (qualified by beforeErrorSampling),
    // 0.0 in development to prevent dev HMR/reloads from consuming monthly replay limits
    replaysOnErrorSampleRate: isProd ? 1.0 : 0.0
  })
}
