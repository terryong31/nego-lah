import type { CSSProperties } from 'react'
import { C } from './theme'

/**
 * The hero's Memphis accents (frontend `MemphisCharacters.vue`), drawn from
 * the same paths so the film and the page are visibly one family.
 */

type ShapeProps = {
  size: number
  color?: string
  style?: CSSProperties
}

const box = (size: number, style?: CSSProperties): CSSProperties => ({
  position: 'absolute',
  width: size,
  height: size,
  overflow: 'visible',
  ...style
})

/** Orange arch with its pink dot. */
export const Arch = ({ size, color = C.orange, style }: ShapeProps) => (
  <svg viewBox="0 0 70 70" fill="none" style={box(size, style)}>
    <path d="M 10 60 A 25 25 0 0 1 60 60" stroke={color} strokeWidth={8} strokeLinecap="round" />
    <circle cx={35} cy={20} r={6} fill={C.red} />
  </svg>
)

/** Eight-point sunburst. */
export const Burst = ({ size, color = C.yellow, style }: ShapeProps) => (
  <svg viewBox="0 0 54 54" style={box(size, style)}>
    <path d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z" fill={color} />
  </svg>
)

/** Purple zigzag. */
export const Zigzag = ({ size, color = C.purple, style }: ShapeProps) => (
  <svg viewBox="0 0 80 40" fill="none" style={box(size, { height: size / 2, ...style })}>
    <path
      d="M 5 20 L 20 5 L 35 35 L 50 5 L 65 35 L 75 20"
      stroke={color}
      strokeWidth={5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
)

/** Dashed turquoise donut with a pink pill. */
export const Donut = ({ size, color = C.cyan, style }: ShapeProps) => (
  <svg viewBox="0 0 60 60" fill="none" style={box(size, style)}>
    <circle cx={30} cy={30} r={18} stroke={color} strokeWidth={6.5} strokeDasharray="14 7" />
    <rect x={42} y={6} width={7} height={16} rx={3.5} fill={C.pink} transform="rotate(35 42 6)" />
  </svg>
)

/** A plain rounded pill. */
export const Pill = ({ size, color = C.pink, style }: ShapeProps) => (
  <div
    style={{
      ...box(size, style),
      height: size * 0.36,
      borderRadius: size,
      background: color
    }}
  />
)

/** A solid dot. */
export const Dot = ({ size, color = C.red, style }: ShapeProps) => (
  <div style={{ ...box(size, style), borderRadius: '50%', background: color }} />
)

/** A loose squiggle. */
export const Squiggle = ({ size, color = C.green, style }: ShapeProps) => (
  <svg viewBox="0 0 100 30" fill="none" style={box(size, { height: size * 0.3, ...style })}>
    <path
      d="M 4 15 Q 16 2 28 15 T 52 15 T 76 15 T 96 15"
      stroke={color}
      strokeWidth={7}
      strokeLinecap="round"
    />
  </svg>
)
