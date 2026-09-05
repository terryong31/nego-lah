import * as Sentry from '@sentry/nuxt'
import {
  replayIntegration,
  browserProfilingIntegration,
  consoleLoggingIntegration
} from '@sentry/browser'
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

  const integrations = [
    // 1. Session Replay Integration (Visual reproduction)
    replayIntegration({
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
      // Capture all errors plus fatal exceptions
      beforeErrorSampling: (event) => {
        if (event.level === 'fatal') return true

        const isUnhandled = event.exception?.values?.some(
          val => val.mechanism?.handled === false
        )
        if (isUnhandled) return true

        const statusCode = Number(
          event.tags?.statusCode
          || event.contexts?.response?.status_code
          || event.extra?.status_code
          || 0
        )
        if (statusCode >= 500) return true

        return false
      }
    }),

    // 2. Continuous Browser Profiling (Flame charts & CPU performance)
    browserProfilingIntegration(),

    // 3. Structured Logging (Pipes console.info/warn/error to Sentry Logs)
    consoleLoggingIntegration({
      levels: ['info', 'warn', 'error']
    }),

    // 4. Capture console.error as Sentry Error events
    Sentry.captureConsoleIntegration({ levels: ['error'] })
  ]

  Sentry.init({
    dsn,
    environment: isProd ? 'production' : 'development',
    release: process.env.SENTRY_RELEASE || 'latest',
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
    // Profiles: 20% in production, 100% in development
    profilesSampleRate: isProd ? 0.2 : 1.0,
    integrations,
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
    // replaysSessionSampleRate: 5% of healthy sessions to populate Replays dashboard
    replaysSessionSampleRate: isProd ? 0.05 : 0.0,
    // replaysOnErrorSampleRate: 100% of error sessions captured
    replaysOnErrorSampleRate: isProd ? 1.0 : 0.0
  })
}
