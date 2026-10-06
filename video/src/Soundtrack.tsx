import { Html5Audio, Sequence, getStaticFiles, interpolate } from 'remotion'
import { DURATION, DEAL, END, HOOK, LIST, NEGO, SCENES, SHIP, WIPE, sceneStart } from './timeline'

/**
 * Music and sound effects, placed from the same timeline the pictures use.
 *
 * The files live in `public/audio/` and are NOT committed (ADR-0031): stock
 * licences cover use in a video, not redistribution in a public repo. Each
 * cue names a file by its base name; any of .mp3/.wav/.ogg/.m4a will do, and
 * a missing one is skipped, so the film renders silent until audio is chosen.
 * `audio/CREDITS.md` lists what goes in each slot.
 */

type Sfx = 'pop' | 'whoosh' | 'stamp' | 'message' | 'tick' | 'cash' | 'chime'

const at = (scene: Parameters<typeof sceneStart>[0], local: number) => sceneStart(scene) + local

const CUES: { sfx: Sfx, frame: number, volume?: number }[] = [
  ...HOOK.bubbles.map(f => ({ sfx: 'pop' as const, frame: at('hook', f) })),
  { sfx: 'tick', frame: at('hook', HOOK.seen) },
  // Every scene change: the shape wipe.
  ...SCENES.slice(1).map(s => ({ sfx: 'whoosh' as const, frame: s.from - WIPE, volume: 0.7 })),
  { sfx: 'stamp', frame: at('list', LIST.tag) },
  { sfx: 'pop', frame: at('list', LIST.listed) },
  ...NEGO.messages.map(m => ({ sfx: 'message' as const, frame: at('nego', m.at) })),
  ...NEGO.messages.filter(m => 'price' in m).map(m => ({ sfx: 'tick' as const, frame: at('nego', m.at + 4) })),
  { sfx: 'stamp', frame: at('deal', DEAL.stamp + 2), volume: 0.9 },
  { sfx: 'cash', frame: at('deal', DEAL.paid) },
  ...SHIP.stops.slice(1).map(stop => ({
    sfx: 'tick' as const,
    frame: at('ship', Math.round(SHIP.depart + (SHIP.arrive - SHIP.depart) * stop))
  })),
  { sfx: 'chime', frame: at('end', END.mark) },
  { sfx: 'pop', frame: at('end', END.url) }
]

/** Frames of the music file to skip (Sub_Clair "Background Music" starts quiet). */
const MUSIC_LEAD_IN = 27

const AUDIO_EXT = /\.(mp3|wav|ogg|m4a|aac)$/i

/** `audio/pop.wav` → `pop`, for every audio file actually present. */
function available() {
  const files = new Map<string, string>()
  for (const file of getStaticFiles()) {
    const match = /^audio\/([^/]+)$/.exec(file.name)
    if (match && AUDIO_EXT.test(match[1]!)) files.set(match[1]!.replace(AUDIO_EXT, ''), file.src)
  }
  return files
}

export const Soundtrack = () => {
  const files = available()
  const music = files.get('music')

  return (
    <>
      {music && (
        <Html5Audio
          src={music}
          // The track opens on ~0.9 s of near-silence; start on the groove.
          trimBefore={MUSIC_LEAD_IN}
          // Straight in, out over the last second; sits under the SFX.
          volume={f => interpolate(f, [0, 4, DURATION - 30, DURATION], [0, 0.42, 0.42, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp'
          })}
        />
      )}
      {CUES.map(({ sfx, frame, volume = 0.7 }, i) => {
        const src = files.get(sfx)
        if (!src) return null
        return (
          <Sequence key={i} from={frame} durationInFrames={Math.min(60, DURATION - frame)} layout="none">
            <Html5Audio src={src} volume={volume} />
          </Sequence>
        )
      })}
    </>
  )
}
