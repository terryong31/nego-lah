export const DEFAULT_ERROR_MESSAGE = 'Something went wrong. Please try again.'

interface ErrorShape {
  statusCode?: unknown
  status?: unknown
  response?: { status?: unknown } | null
  data?: { detail?: unknown } | null
}

function getStatusCode(err: unknown): number | undefined {
  if (!err || typeof err !== 'object') return undefined
  const e = err as ErrorShape
  const raw = e.statusCode ?? e.status ?? e.response?.status
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : undefined
}

/** True when `err` represents an HTTP 5xx server failure. */
export function isServerError(err: unknown): boolean {
  const status = getStatusCode(err)
  return status !== undefined && status >= 500
}

/**
 * Extract a safe user-facing error message for toasts and banners.
 *
 * 5xx responses, raw `ofetch` FetchError strings (`[POST] "...": 500 ...`),
 * network failures, and unhandled JS exceptions always resolve to `fallback`.
 * Only intentional 4xx `data.detail` strings from the API are surfaced.
 */
export function getErrorMessage(err: unknown, fallback = DEFAULT_ERROR_MESSAGE): string {
  if (!err || typeof err !== 'object') return fallback
  if (isServerError(err)) return fallback

  const detail = (err as ErrorShape).data?.detail
  if (typeof detail === 'string') {
    const trimmed = detail.trim()
    if (trimmed) return trimmed
  }

  return fallback
}
