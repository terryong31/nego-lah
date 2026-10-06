import { loadFont as loadDisplay } from '@remotion/google-fonts/BricolageGrotesque'
import { loadFont as loadUi } from '@remotion/google-fonts/PublicSans'

/**
 * The look, as constants (SPEC-100).
 *
 * The site's own Corporate Memphis palette (the hero's arch, sunburst, zigzag
 * and donut), pushed harder: flat colour fields, thick ink outlines and hard
 * offset shadows. Banned on purpose: crossfades, blur-ins, 3D flips,
 * gradients, glows, glass, beige/terracotta palettes, Inter.
 */

export const WIDTH = 1920
export const HEIGHT = 1080
export const FPS = 30

/** ~118–120 BPM (the music bed): something lands on every beat. */
export const BEAT = 15

import { C } from './palette'

export { C }

export const STROKE = 6

/** A Memphis shadow: offset, solid, never blurred. */
export const hardShadow = (size = 12, color: string = C.ink) => `${size}px ${size}px 0 ${color}`

/** Display type for the kinetic words; the UI keeps the app's own Public Sans. */
export const DISPLAY = loadDisplay('normal', { weights: ['800'], subsets: ['latin'] }).fontFamily
export const UI = loadUi('normal', { weights: ['500', '700', '800'], subsets: ['latin'] }).fontFamily

/** Spring presets. Everything overshoots a little; nothing eases linearly. */
export const SNAP = { damping: 14, stiffness: 340, mass: 0.5 }
export const SLAM = { damping: 10, stiffness: 420, mass: 0.7 }
export const FLOAT = { damping: 18, stiffness: 170, mass: 0.8 }
