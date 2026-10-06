/**
 * Storyboard stills (SPEC-100): a few frames per scene into `out/stills/`,
 * so the look can be reviewed before a full render.
 *
 *   mise run video:still            # every scene
 *   mise run video:still -- nego    # one scene
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { SCENES, WIPE } from '../src/timeline.ts'

const only = process.argv[2]
mkdirSync('out/stills', { recursive: true })

for (const scene of SCENES) {
  if (only && scene.id !== only) continue
  // Early, middle and settled — the settled one stops short of the next wipe.
  const frames = [0.25, 0.55, 0.92].map(f => scene.from + Math.min(Math.round(scene.duration * f), scene.duration - WIPE - 1))
  for (const frame of frames) {
    const out = `out/stills/${scene.id}-${String(frame).padStart(4, '0')}.png`
    execFileSync('bunx', ['remotion', 'still', 'NegoLahIntro', out, `--frame=${frame}`, '--log=error'], { stdio: 'inherit' })
    console.log(`🖼  ${out}`)
  }
}
