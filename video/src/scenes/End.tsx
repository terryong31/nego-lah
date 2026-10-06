import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { pop, progress } from '../motion'
import { Arch, Burst, Donut, Dot, Pill, Zigzag } from '../shapes'
import { C, FLOAT, SLAM, STROKE, UI } from '../theme'
import { END } from '../timeline'
import { Mark } from '../ui/parts'
import { SlamText } from '../ui/SlamText'

/** Where each accent comes to rest, and the edge it flies in from. */
const ORBIT = [
  { Shape: Arch, size: 170, x: 250, y: 170, fromX: -400, fromY: -300 },
  { Shape: Burst, size: 150, x: 1540, y: 150, fromX: 2300, fromY: -300 },
  { Shape: Zigzag, size: 220, x: 220, y: 820, fromX: -500, fromY: 1300 },
  { Shape: Donut, size: 170, x: 1560, y: 780, fromX: 2300, fromY: 1300 },
  { Shape: Pill, size: 170, x: 1300, y: 90, fromX: 1300, fromY: -300 },
  { Shape: Dot, size: 56, x: 560, y: 900, fromX: 560, fromY: 1300 }
]

const TAGLINE = ['You', 'list.', 'The', 'AI', 'haggles.', 'You', 'get', 'paid.']

/** The sign-off. The last frame is also the poster, so it must stand alone. */
export const End = () => {
  const frame = useCurrentFrame()
  const mark = pop(frame, END.mark, SLAM)
  const wave = progress(frame, END.wave, END.wave + 10)
  const url = pop(frame, END.url, SLAM)

  return (
    <AbsoluteFill style={{ background: C.paper, overflow: 'hidden' }}>
      {ORBIT.map(({ Shape, size, x, y, fromX, fromY }, i) => {
        const s = pop(frame, END.shapes + i * 2, FLOAT)
        const bob = Math.sin((frame + i * 11) / 10) * 10
        return (
          <Shape
            key={i}
            size={size}
            style={{
              left: fromX + (x - fromX) * s,
              top: fromY + (y - fromY) * s + bob,
              transform: `rotate(${(1 - s) * 180}deg)`
            }}
          />
        )
      })}

      <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 36 }}>
          <div style={{ transform: `scale(${mark}) rotate(${(1 - mark) * -40}deg)` }}>
            <Mark size={210} />
          </div>
          <div style={{ position: 'relative' }}>
            <SlamText text="Nego-lah" at={END.word} size={230} color={C.ink} shadow={C.green} />
            {/* The hero's wave underline, drawn on. */}
            <svg
              viewBox="0 0 100 12"
              preserveAspectRatio="none"
              style={{ position: 'absolute', left: 0, bottom: -34, width: '100%', height: 40, overflow: 'visible' }}
            >
              <path
                d="M 0 6 Q 25 12 50 6 T 100 6"
                stroke={C.green}
                strokeWidth={4.5}
                strokeLinecap="round"
                fill="none"
                pathLength={1}
                strokeDasharray={1}
                strokeDashoffset={1 - wave}
              />
            </svg>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 16, marginTop: 80, fontFamily: UI, fontWeight: 700, fontSize: 52, color: C.ink }}>
          {TAGLINE.map((word, i) => {
            const s = pop(frame, END.tagline + i)
            const hot = word === 'haggles.'
            return (
              <span
                key={i}
                style={{
                  display: 'inline-block',
                  transform: `translateY(${(1 - s) * 50}px) scale(${s})`,
                  ...(hot ? { background: C.yellow, padding: '0 12px', borderRadius: 10, border: `4px solid ${C.ink}` } : {})
                }}
              >
                {word}
              </span>
            )
          })}
        </div>

        <div
          style={{
            marginTop: 56,
            padding: '18px 44px',
            borderRadius: 999,
            background: C.ink,
            border: `${STROKE}px solid ${C.ink}`,
            fontFamily: UI,
            fontWeight: 800,
            fontSize: 46,
            color: C.paper,
            transform: `scale(${url})`
          }}
        >
          negolah.my
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  )
}
