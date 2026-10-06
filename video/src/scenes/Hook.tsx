import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { fall, pop } from '../motion'
import { Arch, Burst, Squiggle } from '../shapes'
import { C, FLOAT, SLAM, UI, hardShadow } from '../theme'
import { HOOK } from '../timeline'
import { Avatar, Check } from '../ui/parts'
import { SlamText } from '../ui/SlamText'

/**
 * The hero's question, answered. "Is this still available?" piles up from
 * strangers, gets read, and every one of them falls off the screen.
 */

const PILE = [
  { x: 110, y: 120, r: -6, shadow: C.pink },
  { x: 1060, y: 90, r: 5, shadow: C.yellow },
  { x: 560, y: 330, r: -3, shadow: C.cyan },
  { x: 1200, y: 420, r: 7, shadow: C.orange },
  { x: 180, y: 560, r: 4, shadow: C.purple },
  { x: 820, y: 680, r: -8, shadow: C.green }
]

const Bubble = ({ index }: { index: number }) => {
  const frame = useCurrentFrame()
  const spot = PILE[index]!
  const at = HOOK.bubbles[index]!
  const s = pop(frame, at, SLAM)
  const seen = pop(frame, HOOK.seen + index)
  const dropAt = HOOK.drop + index * 2
  const y = spot.y + fall(frame, dropAt)
  const spin = Math.max(0, frame - dropAt) * (index % 2 ? 1.6 : -1.6)

  return (
    <div
      style={{
        position: 'absolute',
        left: spot.x,
        top: y,
        display: 'flex',
        alignItems: 'center',
        gap: 22,
        padding: '22px 34px 22px 22px',
        background: C.paper,
        border: `6px solid ${C.ink}`,
        borderRadius: 999,
        boxShadow: hardShadow(12, spot.shadow),
        transform: `rotate(${spot.r + spin}deg) scale(${s})`,
        fontFamily: UI,
        fontWeight: 700,
        fontSize: 46,
        color: C.ink,
        whiteSpace: 'nowrap'
      }}
    >
      <Avatar kind="buyer" size={66} />
      Is this still available?
      <div style={{ display: 'flex', marginLeft: 4, transform: `scale(${seen})` }}>
        <Check size={34} color={C.cyan} />
        <div style={{ marginLeft: -20 }}>
          <Check size={34} color={C.cyan} />
        </div>
      </div>
    </div>
  )
}

export const Hook = () => {
  const frame = useCurrentFrame()
  const ghost = pop(frame, HOOK.ghost + 10, FLOAT)
  const drift = Math.sin(frame / 7) * 14

  return (
    <AbsoluteFill style={{ background: C.ink, overflow: 'hidden' }}>
      <Burst size={160} style={{ left: 1660, top: 760, transform: `rotate(${frame * 2}deg)` }} />
      <Arch size={130} style={{ left: 60, top: 860, transform: `translateY(${drift}px)` }} />
      <Squiggle size={220} style={{ left: 1580, top: 120, transform: `translateY(${-drift}px)` }} />

      {PILE.map((_, i) => <Bubble key={i} index={i} />)}

      <AbsoluteFill style={{ justifyContent: 'center', paddingLeft: 150 }}>
        {/* The hero's own claim, word for word: "up to 80%" of askers ghost. */}
        <SlamText text="Up to 80%" at={HOOK.ghost} size={220} shadow={C.purple} />
        <SlamText text="ghost you." at={HOOK.ghost + 8} size={220} color={C.yellow} shadow={C.pink} style={{ marginTop: 10 }} />
      </AbsoluteFill>

      {/* The ghost itself, flat and purple. */}
      <svg
        viewBox="0 0 120 140"
        style={{
          position: 'absolute',
          left: 1420,
          top: 360,
          width: 300,
          height: 350,
          transform: `translateY(${drift}px) scale(${ghost}) rotate(${(1 - ghost) * 30}deg)`
        }}
      >
        <path
          d="M10 60 C10 25 35 6 60 6 C85 6 110 25 110 60 L110 130 L95 116 L80 130 L65 116 L50 130 L35 116 L20 130 L10 120 Z"
          fill={C.paper}
          stroke={C.purple}
          strokeWidth={7}
          strokeLinejoin="round"
        />
        <circle cx={44} cy={58} r={8} fill={C.ink} />
        <circle cx={78} cy={58} r={8} fill={C.ink} />
        <ellipse cx={61} cy={84} rx={9} ry={12} fill={C.ink} />
      </svg>
    </AbsoluteFill>
  )
}
