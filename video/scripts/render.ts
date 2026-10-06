/**
 * Render the homepage intro (SPEC-100, ADR-0031).
 *
 * Writes `intro.mp4` (H.264 + AAC, FastStart) and `intro.jpg` (the last
 * frame, used as the poster) into the media folder outside the repo, where
 * `mise run media:sync` picks them up. Nothing here ever lands in git.
 */
import { execFileSync } from 'node:child_process'
import { copyFileSync, mkdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { DURATION } from '../src/timeline.ts'

const DEST = (process.env.MEDIA_SOURCE_DIR || join(homedir(), 'Desktop', 'nego-lah-media', 'dist'))
  .replace(/^~(?=$|\/)/, homedir())
const BUDGET_MB = 4

const run = (cmd: string, args: string[]) => execFileSync(cmd, args, { stdio: 'inherit' })

mkdirSync('out', { recursive: true })

run('bunx', [
  'remotion', 'render', 'NegoLahIntro', 'out/intro-raw.mp4',
  '--codec=h264', '--crf=25', '--pixel-format=yuv420p', '--audio-bitrate=128k'
])

// FastStart (moov ahead of mdat) so the browser can start before the end
// arrives — SPEC-099 measured this; keep it explicit rather than assumed.
// The audio passes a limiter at -1 dBFS: stacked SFX on the music peak at 0.
run('ffmpeg', [
  '-y', '-loglevel', 'error', '-i', 'out/intro-raw.mp4',
  '-c:v', 'copy', '-af', 'alimiter=limit=0.891:level=false', '-c:a', 'aac', '-b:a', '128k',
  '-movflags', '+faststart', 'out/intro.mp4'
])

run('bunx', [
  'remotion', 'still', 'NegoLahIntro', 'out/intro.jpg',
  `--frame=${DURATION - 1}`, '--image-format=jpeg', '--jpeg-quality=86'
])

mkdirSync(DEST, { recursive: true })
for (const name of ['intro.mp4', 'intro.jpg']) copyFileSync(join('out', name), join(DEST, name))

const mb = statSync('out/intro.mp4').size / 1024 / 1024
console.log(`\n🎬 intro.mp4 ${mb.toFixed(2)} MB → ${DEST}`)
if (mb > BUDGET_MB) {
  console.error(`❌ Over the ${BUDGET_MB} MB budget. Raise --crf and render again.`)
  process.exit(1)
}
console.log('   Next: mise run media:sync')
