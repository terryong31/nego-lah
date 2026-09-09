import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('SPEC-050 — Security Headers & RFC 9116 security.txt', () => {
  const publicDir = resolve(__dirname, '../public')
  const headersPath = resolve(publicDir, '_headers')
  const securityTxtPath = resolve(publicDir, '.well-known/security.txt')

  it('declares Strict-Transport-Security in public/_headers for all routes', () => {
    expect(existsSync(headersPath)).toBe(true)
    const headersContent = readFileSync(headersPath, 'utf-8')

    // Find the /* section
    const rootBlockMatch = headersContent.match(/\/\*\n([\s\S]*?)(?=\n\/|\n$|$)/)
    expect(rootBlockMatch).not.toBeNull()
    const rootBlock = rootBlockMatch ? rootBlockMatch[1] : ''

    expect(rootBlock).toContain('Strict-Transport-Security: max-age=31536000; includeSubDomains; preload')
  })

  it('declares Content-Type for /.well-known/security.txt in public/_headers', () => {
    const headersContent = readFileSync(headersPath, 'utf-8')
    expect(headersContent).toContain('/.well-known/security.txt')
    expect(headersContent).toContain('text/plain; charset=utf-8')
  })

  it('provides a valid RFC 9116 security.txt file', () => {
    expect(existsSync(securityTxtPath)).toBe(true)
    const content = readFileSync(securityTxtPath, 'utf-8')

    expect(content).toMatch(/^Contact:\s*mailto:/m)
    expect(content).toMatch(/^Expires:\s*\d{4}-\d{2}-\d{2}T/m)
    expect(content).toMatch(/^Canonical:\s*https:\/\/negolah\.my\/\.well-known\/security\.txt/m)
    expect(content).toMatch(/^Preferred-Languages:\s*/m)
  })
})
