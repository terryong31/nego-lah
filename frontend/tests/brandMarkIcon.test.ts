// The Nuxt app tsconfig this file resolves against sets `types: []` (SPA/browser
// context), so Node globals and builtin module types must be pulled in explicitly.
/// <reference types="node" />

import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// The chat "cooking" indicator swaps Nuxt UI's default spinner for the brand
// mark, which reaches <UChatTool> as a normal `i-nego-mark` icon name via a
// @nuxt/icon custom collection. That only works if the SVG obeys the icon
// contract below — a hardcoded fill or a baked-in width would silently ignore
// `text-default`/`size-4` and there is no runtime error to catch it.
describe('Brand mark icon (app/assets/icons/mark.svg)', () => {
  const iconPath = resolve(__dirname, '../app/assets/icons/mark.svg')
  const configPath = resolve(__dirname, '../nuxt.config.ts')

  it('exists at app/assets/icons/mark.svg', () => {
    expect(existsSync(iconPath)).toBe(true)
  })

  it('is themeable: every colour is currentColor, with no baked-in palette values', () => {
    const svg = readFileSync(iconPath, 'utf8')
    expect(svg).toContain('currentColor')
    // No hex literals, named colours or gradients — those would override
    // `text-default` and break dark mode.
    expect(svg).not.toMatch(/#[0-9a-f]{3,8}\b/i)
    expect(svg).not.toMatch(/<linearGradient|<radialGradient/i)
    expect(svg).not.toMatch(/(fill|stroke)=["'](?!none|currentColor)[^"']+["']/i)
  })

  it('is sized by CSS: viewBox only, no width/height attributes', () => {
    const svg = readFileSync(iconPath, 'utf8')
    expect(svg).toMatch(/viewBox=/)
    expect(svg).not.toMatch(/<svg[^>]*\swidth=/i)
    expect(svg).not.toMatch(/<svg[^>]*\sheight=/i)
  })

  it('is registered as the `nego` custom collection and bundled for the SPA', () => {
    const config = readFileSync(configPath, 'utf8')
    expect(config).toContain('customCollections')
    expect(config).toMatch(/prefix:\s*['"]nego['"]/)
    expect(config).toMatch(/dir:\s*['"]\.\/app\/assets\/icons['"]/)
    // ssr: false means there is no icon server in production — the collection
    // must ship inside the client bundle or the mark renders as nothing.
    expect(config).toMatch(/includeCustomCollections:\s*true/)
  })
})

describe('Brand hop animation (app/assets/css/main.css)', () => {
  const cssPath = resolve(__dirname, '../app/assets/css/main.css')

  it('defines a brand-hop keyframe that jumps and spins on the Y axis', () => {
    const css = readFileSync(cssPath, 'utf8')
    expect(css).toContain('@keyframes brand-hop')
    expect(css).toContain('.animate-brand-hop')
    expect(css).toMatch(/rotateY/)
  })

  it('keeps the jump small — no hop larger than 4px', () => {
    const css = readFileSync(cssPath, 'utf8')
    const block = css.slice(css.indexOf('@keyframes brand-hop'))
    const hops = [...block.slice(0, block.indexOf('}\n\n')).matchAll(/translateY\((-?[\d.]+)px\)/g)]
      .map(m => Math.abs(Number(m[1])))
    expect(hops.length).toBeGreaterThan(0)
    expect(Math.max(...hops)).toBeLessThanOrEqual(4)
  })

  it('is disabled under prefers-reduced-motion', () => {
    const css = readFileSync(cssPath, 'utf8')
    const reducedBlocks = css.split('@media (prefers-reduced-motion: reduce)').slice(1)
    expect(reducedBlocks.some(b => b.slice(0, 400).includes('.animate-brand-hop'))).toBe(true)
  })
})
