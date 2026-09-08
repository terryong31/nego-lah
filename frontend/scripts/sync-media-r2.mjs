#!/usr/bin/env node
/**
 * SPEC-045 — upload the optimized demo media to Cloudflare R2.
 *
 * The master copies live OUTSIDE the repo (a ~13 MB binary does not belong in
 * git history). MEDIA_SOURCE_DIR points at a folder holding ONLY the release
 * files — every playable file directly in it is pushed to
 * `r2://<bucket>/videos/<name>` with a 1-year immutable cache header
 * (subdirectories, e.g. `masters/`, are ignored). Default:
 * `~/Desktop/nego-lah-media/dist`.
 *
 * Auth: run `wrangler login` once (personal op — the video changes ~never). No
 * API token or Infisical secret is involved. If a CI job ever needs to run this,
 * set CLOUDFLARE_API_TOKEN (Workers R2 Storage: Edit) in the environment — the
 * repo already carries a `CLOUDFLARE_API_TOKEN` GitHub Actions secret for the
 * Pages deploy; add R2 scope to that one rather than minting a parallel token.
 *
 *   mise run media:sync
 *
 * The account id and bucket are not secrets (account ids appear in dashboard
 * URLs); override with CLOUDFLARE_ACCOUNT_ID / R2_BUCKET / MEDIA_SOURCE_DIR.
 */
import { readdirSync, existsSync, statSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { homedir } from 'node:os'
import { join, extname, basename } from 'node:path'

const ACCOUNT_ID = process.env.CLOUDFLARE_ACCOUNT_ID || '1468deed5e6c65d715d2d969fb9f1f0e'
const BUCKET = process.env.R2_BUCKET || 'nego-lah-media'
const KEY_PREFIX = 'videos'
const SOURCE_DIR = (process.env.MEDIA_SOURCE_DIR || join(homedir(), 'Desktop', 'nego-lah-media', 'dist'))
  .replace(/^~(?=$|\/)/, homedir())

const CONTENT_TYPES = {
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mov': 'video/quicktime',
  '.m4v': 'video/x-m4v',
  '.ogv': 'video/ogg'
}
const CACHE_CONTROL = 'public, max-age=31536000, immutable'

if (!process.env.CLOUDFLARE_API_TOKEN) {
  console.log('ℹ️  No CLOUDFLARE_API_TOKEN — using your `wrangler login` session.')
}

if (!existsSync(SOURCE_DIR)) {
  console.error(`❌ Media source dir not found: ${SOURCE_DIR}`)
  console.error('   Set MEDIA_SOURCE_DIR or drop the encoded files there.')
  process.exit(1)
}

const files = readdirSync(SOURCE_DIR)
  .filter(name => extname(name).toLowerCase() in CONTENT_TYPES)
  .filter(name => !/-original\.[^.]+$/i.test(name))
  .filter(name => statSync(join(SOURCE_DIR, name)).isFile())

if (files.length === 0) {
  console.error(`❌ No uploadable media in ${SOURCE_DIR}`)
  process.exit(1)
}

console.log(`🚀 Uploading ${files.length} file(s) from ${SOURCE_DIR} → r2://${BUCKET}/${KEY_PREFIX}/`)

for (const name of files) {
  const filePath = join(SOURCE_DIR, name)
  const key = `${BUCKET}/${KEY_PREFIX}/${name}`
  const contentType = CONTENT_TYPES[extname(name).toLowerCase()]
  const sizeMb = (statSync(filePath).size / 1024 / 1024).toFixed(2)

  console.log(`\n⬆️  ${basename(name)} (${sizeMb} MB, ${contentType})`)
  execFileSync(
    'bunx',
    [
      'wrangler', 'r2', 'object', 'put', key,
      `--file=${filePath}`,
      `--content-type=${contentType}`,
      `--cache-control=${CACHE_CONTROL}`,
      '--remote',
      '--force'
    ],
    {
      stdio: 'inherit',
      env: { ...process.env, CLOUDFLARE_ACCOUNT_ID: ACCOUNT_ID, WRANGLER_SEND_METRICS: 'false' }
    }
  )
}

const base = process.env.NUXT_PUBLIC_MEDIA_CDN_URL || 'https://media.negolah.my'
console.log('\n🎉 Done. Live at:')
for (const name of files) console.log(`   🔗 ${base}/${KEY_PREFIX}/${name}`)
