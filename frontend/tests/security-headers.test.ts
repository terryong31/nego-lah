import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { contentSecurityPolicy } from '../build/csp'

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

describe('audit SEC-4 — one CSP, served as written', () => {
  const headersContent = readFileSync(resolve(__dirname, '../public/_headers'), 'utf-8')
  const served = headersContent.match(/^ {2}Content-Security-Policy: (.*)$/m)?.[1]

  it('serves exactly the production policy from build/csp.ts', () => {
    expect(served).toBe(contentSecurityPolicy({ dev: false }))
  })

  it('does not allow the retired Supabase browser channel or localhost in production', () => {
    const prod = contentSecurityPolicy({ dev: false })
    expect(prod).not.toMatch(/supabase\.co/)
    expect(prod).not.toMatch(/localhost|127\.0\.0\.1/)
  })

  it('still lets the dev server reach the local API', () => {
    expect(contentSecurityPolicy({ dev: true })).toMatch(/http:\/\/localhost:8000/)
  })
})
