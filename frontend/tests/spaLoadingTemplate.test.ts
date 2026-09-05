// The Nuxt app tsconfig this file resolves against sets `types: []` (SPA/browser
// context), so Node globals and builtin module types must be pulled in explicitly.
/// <reference types="node" />

import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('SPA Loading Template (app/spa-loading-template.html)', () => {
  const templatePath = resolve(__dirname, '../app/spa-loading-template.html')

  it('file exists at app/spa-loading-template.html', () => {
    expect(existsSync(templatePath)).toBe(true)
  })

  it('contains the __nuxt-loader root container with role="status"', () => {
    const html = readFileSync(templatePath, 'utf8')
    expect(html).toContain('id="__nuxt-loader"')
    expect(html).toContain('role="status"')
    expect(html).toContain('aria-label')
  })

  it('uses purely inline CSS and contains no external network stylesheet or script references', () => {
    const html = readFileSync(templatePath, 'utf8')
    expect(html).toContain('<style>')
    expect(html).toContain('</style>')

    // Zero external network resource calls (no external css, images, or scripts)
    expect(html).not.toMatch(/href=["']https?:\/\//i)
    expect(html).not.toMatch(/src=["']https?:\/\//i)
    expect(html).not.toMatch(/url\(["']?https?:\/\//i)
    expect(html).not.toMatch(/<script/i)
    expect(html).not.toMatch(/<link/i)
  })

  it('defaults to system prefers-color-scheme while supporting site-declared light and dark modes', () => {
    const html = readFileSync(templatePath, 'utf8')
    // Default system preference support
    expect(html).toContain('@media (prefers-color-scheme: dark)')

    // Explicit site-declared light mode override (even under system dark mode)
    expect(html).toContain('html.light')
    expect(html).toContain('--loader-bg: #ffffff')
    expect(html).toContain('--loader-text: #09090b')

    // Explicit site-declared dark mode override
    expect(html).toContain('html.dark')
    expect(html).toContain('--loader-bg: #09090b')
    expect(html).toContain('--loader-text: #fafafa')
  })

  it('renders the Nego-Lah brand logo SVG and title', () => {
    const html = readFileSync(templatePath, 'utf8')
    expect(html).toContain('<svg')
    expect(html).toContain('Nego-Lah')
  })

  it('features jump and 3D rotation (translateY, rotateY) animation and removes backglow, progress bar & rounded card', () => {
    const html = readFileSync(templatePath, 'utf8')
    // Jump and spin keyframes
    expect(html).toContain('rotateY')
    expect(html).toContain('loaderJump')
    expect(html).toContain('loaderSpin')

    // Backglow must be removed
    expect(html).not.toContain('loader-icon-glow')
    expect(html).not.toContain('loaderGlowPulse')

    // Progress bar must be removed
    expect(html).not.toContain('loader-progress-track')
    expect(html).not.toContain('loader-progress-bar')

    // Rounded card background must be removed
    expect(html).not.toContain('--loader-card-bg')
    expect(html).not.toContain('--loader-card-border')
  })
})
