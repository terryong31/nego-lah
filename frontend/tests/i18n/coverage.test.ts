import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import en from '../../app/locales/en.json'
import ms from '../../app/locales/ms.json'
import zh from '../../app/locales/zh.json'

function flattenKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  let keys: string[] = []
  for (const k of Object.keys(obj)) {
    const full = prefix ? `${prefix}.${k}` : k
    const val = obj[k]
    if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
      keys = keys.concat(flattenKeys(val as Record<string, unknown>, full))
    } else {
      keys.push(full)
    }
  }
  return keys
}

function getLeaves(obj: Record<string, unknown>): Array<{ key: string, value: unknown }> {
  let leaves: Array<{ key: string, value: unknown }> = []
  for (const k of Object.keys(obj)) {
    const val = obj[k]
    if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
      const sub = getLeaves(val as Record<string, unknown>)
      leaves = leaves.concat(sub.map(s => ({ key: `${k}.${s.key}`, value: s.value })))
    } else {
      leaves.push({ key: k, value: val })
    }
  }
  return leaves
}

describe('i18n Locale Coverage & Parity', () => {
  const enKeys = new Set(flattenKeys(en))
  const msKeys = new Set(flattenKeys(ms))
  const zhKeys = new Set(flattenKeys(zh))

  it('enforces 100% key parity between English and Malay', () => {
    const missingInMs = [...enKeys].filter(k => !msKeys.has(k))
    const extraInMs = [...msKeys].filter(k => !enKeys.has(k))

    expect(missingInMs, `Keys in en.json missing from ms.json: ${missingInMs.join(', ')}`).toEqual([])
    expect(extraInMs, `Keys in ms.json not found in en.json: ${extraInMs.join(', ')}`).toEqual([])
  })

  it('enforces 100% key parity between English and Chinese', () => {
    const missingInZh = [...enKeys].filter(k => !zhKeys.has(k))
    const extraInZh = [...zhKeys].filter(k => !enKeys.has(k))

    expect(missingInZh, `Keys in en.json missing from zh.json: ${missingInZh.join(', ')}`).toEqual([])
    expect(extraInZh, `Keys in zh.json not found in en.json: ${extraInZh.join(', ')}`).toEqual([])
  })

  it('ensures no translation entries are empty or whitespace-only', () => {
    const locales = [
      { name: 'en', data: en },
      { name: 'ms', data: ms },
      { name: 'zh', data: zh }
    ]

    for (const { name, data } of locales) {
      const leaves = getLeaves(data)
      for (const { key, value } of leaves) {
        expect(typeof value === 'string', `Locale ${name} key "${key}" must be a string`).toBe(true)
        expect((value as string).trim().length > 0, `Locale ${name} key "${key}" is empty`).toBe(true)
      }
    }
  })

  it('ensures referenced i18n keys in source files exist in en.json', () => {
    function scanFiles(dir: string): string[] {
      let results: string[] = []
      const entries = fs.readdirSync(dir, { withFileTypes: true })
      for (const entry of entries) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          if (!['node_modules', '.nuxt', '.output', 'dist', '.git', 'locales'].includes(entry.name)) {
            results = results.concat(scanFiles(full))
          }
        } else if (entry.name.endsWith('.vue') || entry.name.endsWith('.ts')) {
          results.push(full)
        }
      }
      return results
    }

    const sourceFiles = scanFiles(path.resolve(__dirname, '../../app'))
    // Match calls like $t('key.name'), t("key.name"), te('key.name')
    const tRegex = /(?:(?:\$t|(?<=[^a-zA-Z0-9_])t|te)\s*\(\s*['"`]([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)['"`]\))/g

    const missingKeys: Array<{ file: string, key: string }> = []

    for (const file of sourceFiles) {
      const content = fs.readFileSync(file, 'utf8')
      let match: RegExpExecArray | null
      while ((match = tRegex.exec(content)) !== null) {
        const key = match[1]!
        if (!enKeys.has(key)) {
          missingKeys.push({ file: path.relative(path.resolve(__dirname, '../../..'), file), key })
        }
      }
    }

    expect(
      missingKeys,
      `Referenced translation keys missing from en.json: ${JSON.stringify(missingKeys, null, 2)}`
    ).toEqual([])
  })
})
