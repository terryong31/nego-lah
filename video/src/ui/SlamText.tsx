import type { CSSProperties } from 'react'
import { useCurrentFrame } from 'remotion'
import { pop } from '../motion'
import { C, DISPLAY, SLAM } from '../theme'

type Props = {
  text: string
  at: number
  size: number
  color?: string
  /** Colour of the hard offset behind each letter. */
  shadow?: string
  /** Frames between letters. */
  stagger?: number
  style?: CSSProperties
}

/**
 * Kinetic display type: each letter drops in rotated and overshoots into
 * place. No fades, no blur — a letter is either not there or slammed down.
 */
export const SlamText = ({ text, at, size, color = C.paper, shadow = C.pink, stagger = 1, style }: Props) => {
  const frame = useCurrentFrame()
  const offset = Math.max(4, Math.round(size / 16))

  return (
    <div
      style={{
        fontFamily: DISPLAY,
        fontSize: size,
        lineHeight: 0.92,
        letterSpacing: '-0.03em',
        color,
        whiteSpace: 'pre',
        ...style
      }}
    >
      {[...text].map((ch, i) => {
        const s = pop(frame, at + i * stagger, SLAM)
        return (
          <span
            key={i}
            style={{
              display: 'inline-block',
              transform: `translateY(${(1 - s) * -size * 0.9}px) rotate(${(1 - s) * -14}deg) scale(${s})`,
              textShadow: `${offset}px ${offset}px 0 ${shadow}`
            }}
          >
            {ch}
          </span>
        )
      })}
    </div>
  )
}
