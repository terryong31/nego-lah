import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { easeIn } from '../motion'
import { C, HEIGHT, STROKE, WIDTH } from '../theme'
import type { WipeShape } from '../timeline'

/**
 * A scene change. The next scene's colour arrives as one Memphis shape that
 * grows until it fills the frame, and the cut happens under it — so no frame
 * is ever a mix of two scenes (no crossfades).
 */
export const ShapeWipe = ({ shape, color, duration }: { shape: WipeShape, color: string, duration: number }) => {
  const frame = useCurrentFrame()
  const t = easeIn(Math.min(1, (frame + 1) / duration))
  const diagonal = Math.hypot(WIDTH, HEIGHT)

  if (shape === 'pill') {
    // A fat rounded bar sweeps across on a tilt.
    // Ends centred on the frame, from fully off-screen left.
    const width = WIDTH * 2.2
    return (
      <AbsoluteFill>
        <div
          style={{
            position: 'absolute',
            left: -WIDTH * 2.7 + t * WIDTH * 2.1,
            top: HEIGHT / 2 - diagonal / 2,
            width,
            height: diagonal,
            background: color,
            borderRadius: diagonal,
            border: `${STROKE * 2}px solid ${C.ink}`,
            transform: 'rotate(-18deg)'
          }}
        />
      </AbsoluteFill>
    )
  }

  const size = shape === 'burst' ? diagonal * 2.6 : diagonal * 1.15
  const scale = t
  const rotate = shape === 'burst' ? t * 70 : 0

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      {shape === 'burst'
        ? (
            <svg
              viewBox="0 0 54 54"
              style={{ width: size, height: size, flex: 'none', transform: `scale(${scale}) rotate(${rotate}deg)` }}
            >
              <path
                d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z"
                fill={color}
                stroke={C.ink}
                strokeWidth={0.5}
                strokeLinejoin="round"
              />
            </svg>
          )
        : (
            <div
              style={{
                width: size,
                height: size,
                flex: 'none',
                borderRadius: '50%',
                background: color,
                border: `${STROKE * 2}px solid ${C.ink}`,
                transform: `scale(${scale})`
              }}
            />
          )}
    </AbsoluteFill>
  )
}
