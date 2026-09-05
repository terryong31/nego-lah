/**
 * SPEC-027 — how one stored message becomes bubbles on screen.
 *
 * A newline means whatever the author's input method made it mean. The seller
 * persona is prompted to text one thought per message, so an AI *blank line* is
 * a message boundary. `UChatPrompt` submits on Enter, so a human who typed a
 * newline pressed Shift+Enter and meant "keep this together" — they'd have hit
 * Enter twice for two bubbles. Same character, opposite intent; only the
 * authorship tells them apart.
 *
 * Within an AI turn the boundary is a BLANK line, not any newline, so lines
 * that belong together — a shipping address, a list of items, a spec sheet —
 * stay in one bubble instead of being shredded into one bubble per line. This
 * also fails safe: if the model forgets the blank line we get one bubble with
 * line breaks, which reads fine, rather than a wall of one-line bubbles.
 */

/**
 * A markdown link the agent emits for payment, e.g.
 * "[Pay RM71.50 Now](https://buy.stripe.com/...)".
 */
export const PAY_LINK = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/

/** A blank line: the AI's "send" key. Single newlines stay inside a bubble. */
const BUBBLE_BREAK = /\n\s*\n/

/** The opening of a pay link whose closing paren hasn't streamed in yet. */
const PARTIAL_LINK = '](http'

export type Block
  = | { type: 'text', text: string }
    | { type: 'pay', label: string, url: string }
    | { type: 'pending' }

/**
 * Whether this message's blank lines are bubble boundaries.
 *
 * `role` is the primary gate on purpose: `get_history_page` defaults a missing
 * `source` to "ai", so a row written before the column existed would otherwise
 * split a buyer's message. Within the assistant side, `source === 'admin'`
 * marks a seller takeover — a human at a keyboard, so their newlines are lines,
 * not messages. An absent source is a live stream, which only the AI produces.
 */
export function shouldSplit(role?: string, source?: string): boolean {
  return role === 'assistant' && source !== 'admin'
}

/**
 * One bubble's worth of text → the blocks it renders as.
 *
 * Internal single newlines are preserved for `whitespace-pre-wrap` to render;
 * only a pay link is lifted out, so the checkout hand-off card still works when
 * the agent puts the link on the same line as its sentence.
 */
function parseSegment(text: string): Block[] {
  const trimmed = text.trim()
  if (!trimmed) return []

  const match = trimmed.match(PAY_LINK)

  if (!match) {
    const partial = trimmed.indexOf(PARTIAL_LINK)
    if (partial === -1) return [{ type: 'text', text: trimmed }]

    // Link still being typed out. Keep whatever is already readable and hold a
    // placeholder for the link itself, trimming the half-written "[Pay RM50…"
    // label so it doesn't flash as raw markdown.
    const before = trimmed.slice(0, partial).replace(/\[[^[]*$/, '').trim()
    return before ? [{ type: 'text', text: before }, { type: 'pending' }] : [{ type: 'pending' }]
  }

  const blocks: Block[] = []
  const linkStart = match.index ?? 0
  const before = trimmed.slice(0, linkStart).trim()
  const after = trimmed.slice(linkStart + match[0].length).trim()

  if (before) blocks.push({ type: 'text', text: before })
  blocks.push({ type: 'pay', label: match[1]!, url: match[2]! })
  if (after) blocks.push({ type: 'text', text: after })

  return blocks
}

/**
 * Parse one message's text into the bubbles it renders as.
 *
 * `text` is already resolved by the caller, which is what lets the chat page
 * pass the typewriter's partially-revealed text and get bubbles that pop into
 * existence one at a time as blank lines are uncovered.
 */
export function messageBlocks(text: string, split: boolean): Block[] {
  if (!text.trim()) return []
  if (!split) return parseSegment(text)
  return text.split(BUBBLE_BREAK).flatMap(parseSegment)
}
