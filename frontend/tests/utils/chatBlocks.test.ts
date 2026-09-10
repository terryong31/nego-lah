import { describe, expect, it } from 'vitest'
import { isTrustedPaymentUrl, messageBlocks, shouldSplit } from '~/utils/chatBlocks'

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

  // SPEC-056 #4. A PayCard is not a link — it is a branded tile reading "Deal
  // Agreed" over a "Secured by Stripe" badge, and the model that decides what
  // goes in it takes instructions from the buyer. Prompt injection turning a
  // markdown link into a first-party-looking checkout button is the whole
  // attack, so the host, not the model, decides what earns the badge.
  describe('messageBlocks — only Stripe checkout hosts earn a PayCard', () => {
    const payBlock = (text: string) => messageBlocks(text, true)[0]

    it.each([
      ['https://buy.stripe.com/test_abc'],
      ['https://checkout.stripe.com/c/pay/cs_test_123'],
      ['https://checkout.stripe.com/pay/cs_live_x?locale=en'],
      // Stripe serves regional checkout from subdomains of those hosts.
      ['https://link.checkout.stripe.com/c/pay/x']
    ])('renders a card for %s', (url) => {
      expect(payBlock(`[Pay RM50 Now](${url})`)).toEqual({
        type: 'pay',
        label: 'Pay RM50 Now',
        url
      })
    })

    it.each([
      // Outright attacker-controlled.
      ['https://malicious-phishing.com/pay'],
      // The classic suffix trick: the trusted name is a *prefix* of the host.
      ['https://buy.stripe.com.evil.test/pay'],
      // ...and its mirror image, where it appears inside the path or userinfo.
      ['https://evil.test/buy.stripe.com/pay'],
      ['https://buy.stripe.com@evil.test/pay'],
      // A lookalike host that merely contains the trusted string.
      ['https://notbuy.stripe.com.co/pay'],
      // Right host, wrong scheme — a downgraded checkout is not a checkout.
      ['http://buy.stripe.com/test_abc'],
      // Stripe's own marketing site is not a checkout endpoint.
      ['https://stripe.com/pricing']
    ])('leaves %s as plain text, with no Stripe badge around it', (url) => {
      const markdown = `[Pay RM50 Now](${url})`
      expect(payBlock(markdown)).toEqual({ type: 'text', text: markdown })
    })

    it('does not swallow the surrounding sentence when the link is untrusted', () => {
      const blocks = messageBlocks(
        'Deal! Pay here [Pay RM50 Now](https://evil.test/pay) thanks',
        true
      )
      expect(blocks).toEqual([
        { type: 'text', text: 'Deal! Pay here [Pay RM50 Now](https://evil.test/pay) thanks' }
      ])
    })

    it('exports the host check so other callers cannot re-derive it wrongly', () => {
      expect(isTrustedPaymentUrl('https://buy.stripe.com/x')).toBe(true)
      expect(isTrustedPaymentUrl('https://evil.test/x')).toBe(false)
      expect(isTrustedPaymentUrl('not a url at all')).toBe(false)
      expect(isTrustedPaymentUrl('')).toBe(false)
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
