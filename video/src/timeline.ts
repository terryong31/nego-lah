import { C } from './palette'

/**
 * Every timing in the film, in frames at 30 fps. Scenes read their local
 * moments from here and the soundtrack reads the same numbers, so a sound
 * cannot drift from the thing it belongs to.
 */

export type WipeShape = 'circle' | 'burst' | 'pill'

export const SCENES = [
  { id: 'hook', from: 0, duration: 105, bg: C.ink, wipe: 'circle' },
  { id: 'list', from: 105, duration: 105, bg: C.yellow, wipe: 'burst' },
  { id: 'nego', from: 210, duration: 255, bg: C.paper, wipe: 'pill' },
  { id: 'deal', from: 465, duration: 105, bg: C.green, wipe: 'circle' },
  { id: 'ship', from: 570, duration: 105, bg: C.cyan, wipe: 'burst' },
  { id: 'end', from: 675, duration: 135, bg: C.paper, wipe: 'pill' }
] as const satisfies readonly { id: string, from: number, duration: number, bg: string, wipe: WipeShape }[]

export type SceneId = (typeof SCENES)[number]['id']

export const DURATION = SCENES.reduce((end, s) => Math.max(end, s.from + s.duration), 0)

/** How long a shape wipe takes to cover the frame before a cut. */
export const WIPE = 10

export const sceneStart = (id: SceneId) => SCENES.find(s => s.id === id)!.from

/** Local frames inside each scene. */
export const HOOK = {
  bubbles: [0, 5, 10, 15, 20, 25],
  seen: 33,
  drop: 40,
  ghost: 48
}

export const LIST = {
  title: 2,
  card: 8,
  tag: 38,
  listed: 58
}

/**
 * The haggle. Whole numbers, small steps, and the agent holds above a floor
 * the video never shows — the same rules the real agent follows (ADR-0011).
 */
export const NEGO = {
  title: 2,
  messages: [
    { at: 14, from: 'buyer', text: 'Boss, RM100 can?' },
    { at: 48, from: 'agent', text: 'Aiya, too low lah. RM140 ok?', price: 140 },
    { at: 84, from: 'buyer', text: 'RM115 lah?' },
    { at: 118, from: 'agent', text: 'Ok lah, RM132 for you.', price: 132 },
    { at: 154, from: 'buyer', text: 'RM125, final final?' },
    { at: 188, from: 'agent', text: "RM128 and it's yours.", price: 128 },
    { at: 220, from: 'buyer', text: 'Deal!' }
  ],
  /** The agent "types" for this long before each reply lands. */
  typing: 14,
  startPrice: 150
} as const

export const DEAL = {
  tag: 0,
  stamp: 12,
  pay: 38,
  paid: 62
}

export const SHIP = {
  title: 2,
  depart: 14,
  arrive: 78,
  /** Where along the track (0–1) each stop sits. */
  stops: [0, 0.5, 1]
}

export const END = {
  shapes: 0,
  mark: 6,
  word: 10,
  wave: 24,
  tagline: 32,
  url: 48
}
