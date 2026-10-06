import { interpolate, spring } from 'remotion'
import { FPS, SNAP } from './theme'

type SpringConfig = { damping: number, stiffness: number, mass: number }

/** 0 → 1 (with overshoot) starting at `at`; 0 before it. */
export const pop = (frame: number, at: number, config: SpringConfig = SNAP) =>
  spring({ frame: frame - at, fps: FPS, config })

/** Clamped linear 0 → 1 over [from, to] — for progress, never for appearance. */
export const progress = (frame: number, from: number, to: number) =>
  interpolate(frame, [from, to], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })

/** Falling under gravity from `at`: pixels travelled. */
export const fall = (frame: number, at: number, g = 5) => {
  const t = Math.max(0, frame - at)
  return 0.5 * g * t * t
}

/** A decaying shake for impacts. */
export const shake = (frame: number, at: number, amp = 18, decay = 10) => {
  const t = frame - at
  if (t < 0 || t > decay * 3) return { x: 0, y: 0 }
  const k = amp * Math.exp(-t / decay)
  return { x: Math.sin(t * 2.7) * k, y: Math.cos(t * 3.3) * k * 0.6 }
}

/** Ease-in quad, for things that accelerate into a cut. */
export const easeIn = (t: number) => t * t

/** Ease-in-out cubic, for travel. */
export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
