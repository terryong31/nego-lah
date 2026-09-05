import { describe, expect, it } from 'vitest'
import { messageBlocks, shouldSplit } from '~/utils/chatBlocks'

describe('utils/chatBlocks.ts', () => {
  describe('shouldSplit', () => {
    it('splits the AI, which uses a newline to mean "next message"', () => {
      expect(shouldSplit('assistant', 'ai')).toBe(true)
    })

    it('splits a live-streamed turn, which carries no stored source', () => {
      // Only the AI ever streams, so an absent source still means "AI".
      expect(shouldSplit('assistant', undefined)).toBe(true)
      expect(shouldSplit('assistant', '')).toBe(true)
    })

    it('does not split the buyer, whose newline came from Shift+Enter', () => {
      expect(shouldSplit('user', 'human')).toBe(false)
    })

    it('does not split a seller takeover, also a human pressing Shift+Enter', () => {
      expect(shouldSplit('assistant', 'admin')).toBe(false)
    })

    it('gates on role first, so a legacy row without a source is never shredded', () => {
      // get_history_page defaults a missing `source` to "ai"; role has to decide.
      expect(shouldSplit('user', 'ai')).toBe(false)
    })

    it('never splits a system notice', () => {
      expect(shouldSplit('system', 'system')).toBe(false)
    })
  })

  describe('messageBlocks — split (AI)', () => {
    it('gives each blank-line-separated block its own bubble', () => {
      const blocks = messageBlocks('Great choice! 😊\n\nSuper clean condition\n\nRM1,200 firm', true)
      expect(blocks).toEqual([
        { type: 'text', text: 'Great choice! 😊' },
        { type: 'text', text: 'Super clean condition' },
        { type: 'text', text: 'RM1,200 firm' }
      ])
    })

    it('keeps lines that belong together in one bubble — a shipping address', () => {
      // The whole point of splitting on a BLANK line: single newlines inside a
      // block are line breaks, so an address is one bubble, not four.
      const blocks = messageBlocks(
        'Got it! Shipping to:\nTerry Ong\n012-3456789\n12 Jalan Ampang, KL\n\nThanks again! 😊',
        true
      )
      expect(blocks).toEqual([
        { type: 'text', text: 'Got it! Shipping to:\nTerry Ong\n012-3456789\n12 Jalan Ampang, KL' },
        { type: 'text', text: 'Thanks again! 😊' }
      ])
    })

    it('fails safe to one bubble when the model forgets the blank lines', () => {
      const blocks = messageBlocks('Great choice!\nSuper clean condition', true)
      expect(blocks).toEqual([{ type: 'text', text: 'Great choice!\nSuper clean condition' }])
    })

    it('treats a run of several blank lines as one boundary', () => {
      expect(messageBlocks('One\n\n\n\nTwo', true)).toEqual([
        { type: 'text', text: 'One' },
        { type: 'text', text: 'Two' }
      ])
    })

    it('drops blank lines, including residue left by stripping [[STATUS:…]]', () => {
      const blocks = messageBlocks('Checking that for you\n\n   \nAll good!', true)
      expect(blocks).toEqual([
        { type: 'text', text: 'Checking that for you' },
        { type: 'text', text: 'All good!' }
      ])
    })

    it('lifts a pay link out of its block into a payment card', () => {
      const blocks = messageBlocks(
        'Deal! Here you go 🛒\n\n[Pay RM71.50 Now](https://buy.stripe.com/test_abc)',
        true
      )
      expect(blocks).toEqual([
        { type: 'text', text: 'Deal! Here you go 🛒' },
        { type: 'pay', label: 'Pay RM71.50 Now', url: 'https://buy.stripe.com/test_abc' }
      ])
    })

    it('keeps already-streamed text visible while the link is still arriving', () => {
      // The half-written "[Pay RM71.50 Now" label is trimmed so it never flashes
      // as raw markdown before the closing paren lands.
      const blocks = messageBlocks('Sure!\n\n[Pay RM71.50 Now](http', true)
      expect(blocks).toEqual([
        { type: 'text', text: 'Sure!' },
        { type: 'pending' }
      ])
    })

    it('returns nothing for empty or whitespace-only text', () => {
      expect(messageBlocks('', true)).toEqual([])
      expect(messageBlocks('  \n \n', true)).toEqual([])
    })
  })

  describe('messageBlocks — unsplit (human)', () => {
    it('keeps a Shift+Enter message in one bubble with its newlines intact', () => {
      const blocks = messageBlocks('Item ships from KL\nUsually 2-3 days', false)
      expect(blocks).toEqual([
        { type: 'text', text: 'Item ships from KL\nUsually 2-3 days' }
      ])
    })

    it('does not treat a human\'s blank line as a bubble boundary either', () => {
      const blocks = messageBlocks('Hi!\n\nIs this still available?', false)
      expect(blocks).toEqual([{ type: 'text', text: 'Hi!\n\nIs this still available?' }])
    })

    it('still extracts a pay link, preserving the text around it', () => {
      const blocks = messageBlocks(
        'All set!\n[Pay RM71.50 Now](https://buy.stripe.com/test_abc)\nLink expires in 24h',
        false
      )
      expect(blocks).toEqual([
        { type: 'text', text: 'All set!' },
        { type: 'pay', label: 'Pay RM71.50 Now', url: 'https://buy.stripe.com/test_abc' },
        { type: 'text', text: 'Link expires in 24h' }
      ])
    })

    it('holds a placeholder for a half-streamed link, keeping the text before it', () => {
      expect(messageBlocks('Here: [Pay RM71.50 Now](http', false)).toEqual([
        { type: 'text', text: 'Here:' },
        { type: 'pending' }
      ])
    })

    it('holds a bare placeholder when nothing but the link has arrived', () => {
      expect(messageBlocks('[Pay RM71.50 Now](http', false)).toEqual([{ type: 'pending' }])
    })

    it('returns nothing for empty or whitespace-only text', () => {
      expect(messageBlocks('', false)).toEqual([])
      expect(messageBlocks('   \n  ', false)).toEqual([])
    })
  })
})
