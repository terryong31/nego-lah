/**
 * SPEC-093 / SPEC-094 — the guards that keep the credential off the client.
 *
 * Both migrations are easy to undo by accident: one `useSupabaseClient()` for a
 * quick query, one `supabase.channel(...)` for a quick realtime feature, and the
 * token is back in the page and the conversation is back on a public channel.
 * These are source-level assertions, deliberately, because that is the level the
 * regression happens at.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const FRONTEND_ROOT = resolve(__dirname, '..')
const APP_DIR = join(FRONTEND_ROOT, 'app')

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return /\.(ts|vue)$/.test(entry) ? [full] : []
  })
}

/**
 * Comments are stripped first: these files explain at length what they no longer
 * do, and a guard that trips on its own rationale is a guard nobody keeps.
 */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/<!--[\s\S]*?-->/g, '')
}

/** Files whose code — not prose — matches, as repo-relative paths. */
function matching(pattern: RegExp): string[] {
  return sourceFiles(APP_DIR)
    .filter(file => pattern.test(stripComments(readFileSync(file, 'utf8'))))
    .map(file => relative(FRONTEND_ROOT, file))
}

describe('no client-side credentials', () => {
  it('imports no Supabase client anywhere in the app', () => {
    // SPEC-094 removed the last reason for one: realtime moved onto the
    // authenticated SSE stream the notifications already use.
    expect(matching(/from ['"]@supabase\/supabase-js['"]/)).toEqual([])
    expect(matching(/\buseSupabaseClient\b|\buseSupabaseUser\b/)).toEqual([])
  })

  it('declares no Supabase dependency', () => {
    const pkg = JSON.parse(readFileSync(join(FRONTEND_ROOT, 'package.json'), 'utf8'))
    const deps = { ...pkg.dependencies, ...pkg.devDependencies }
    expect(Object.keys(deps).filter(name => name.includes('supabase'))).toEqual([])
  })

  it('never reads a session token out of the page', () => {
    // `getSession()` was how every caller got the bearer token it attached, and
    // `.access_token` was what they read off it. The session is an httpOnly
    // cookie now: there is nothing to read.
    expect(matching(/\.auth\.getSession\(|\.access_token\b/)).toEqual([])
  })

  it('stores nothing auth-shaped in browser storage', () => {
    expect(matching(/(localStorage|sessionStorage)[^\n]*(token|session|auth)/i)).toEqual([])
  })

  it('sends no Authorization header from the buyer app', () => {
    // The admin console never used one either — both are cookie-authenticated.
    expect(matching(/Authorization['"]?\s*:\s*[`'"]Bearer/)).toEqual([])
  })
})
