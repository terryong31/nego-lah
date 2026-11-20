/**
 * Allowlist external URLs to http/https schemes only (SPEC-116 / SEC-19).
 * Prevents javascript:, data:, vbscript:, or other executable schemes from
 * being bound to anchor or Nuxt UI link targets.
 */
export function isSafeHttpUrl(url?: string | null): boolean {
  if (!url || typeof url !== 'string') return false
  const trimmed = url.trim()
  if (!trimmed) return false
  try {
    const parsed = new URL(trimmed)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}
