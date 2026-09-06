import type { ItemTranslation } from './item'

export type TrilingualDraft = Record<string, ItemTranslation>

const LANGS = ['en', 'ms', 'zh'] as const

/**
 * Pull a `{ en: {...}, ms: {...}, zh: {...} }` draft out of whatever the vision
 * model wrote.
 *
 * The model is asked for JSON and usually obliges, but it also fences it in
 * markdown, prefixes it with prose, or leaves an unescaped quote inside a
 * description — so a bare `JSON.parse` fails often enough to matter. This first
 * takes the outermost `{...}` span and parses it; only if that throws does it
 * fall back to pulling each language block out with regexes.
 *
 * Returns null when there is nothing usable, so the caller can leave the form
 * alone rather than overwrite it with blanks.
 */
export function extractTrilingualData(raw: string | undefined): TrilingualDraft | null {
  if (!raw || typeof raw !== 'string') return null

  const clean = raw.trim()
  const start = clean.indexOf('{')
  const end = clean.lastIndexOf('}')
  if (start === -1 || end <= start) return null
  const candidate = clean.slice(start, end + 1)

  try {
    const parsed = JSON.parse(candidate)
    if (parsed && typeof parsed === 'object' && (parsed.en || parsed.ms || parsed.zh)) {
      return parsed
    }
  } catch {
    const salvaged = salvageByRegex(candidate)
    if (salvaged) return salvaged
  }

  return null
}

/** Last resort for JSON the model didn't quite close or escape properly. */
function salvageByRegex(candidate: string): TrilingualDraft | null {
  try {
    const result: TrilingualDraft = {}
    for (const lang of LANGS) {
      const langRegex = new RegExp(`"${lang}"\\s*:\\s*\\{([\\s\\S]*?)\\}(?=\\s*,\\s*"[a-z]{2}"|\\s*\\})`, 'i')
      const langMatch = langRegex.exec(candidate)
      const block = langMatch?.[1]
      if (!block) continue

      const nameM = /"name"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"\w+"|\s*$)/.exec(block)
      const descM = /"description"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"\w+"|\s*$)/.exec(block)
      const condM = /"condition"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"\w+"|\s*$)/.exec(block)
      result[lang] = {
        name: nameM ? unescapeJsonish(nameM[1]) : '',
        description: descM ? unescapeJsonish(descM[1]) : '',
        condition: condM ? condM[1]?.replace(/\\"/g, '"') : ''
      }
    }
    return Object.keys(result).length > 0 ? result : null
  } catch {
    return null
  }
}

function unescapeJsonish(value: string | undefined): string {
  return (value ?? '').replace(/\\"/g, '"').replace(/\\n/g, '\n')
}
