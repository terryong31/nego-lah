import { describe, expect, it } from 'vitest'
import { discountPercent, effectivePrice, formatPrice, hasDiscount, parsePriceFromLabel } from '~/utils/pricing'

describe('utils/pricing.ts', () => {
  describe('hasDiscount', () => {
    it('is true only when a negotiated price sits below the listed price', () => {
      expect(hasDiscount({ price: 1199, discounted_price: 1000 })).toBe(true)
      expect(hasDiscount({ price: 1199, discounted_price: 1199 })).toBe(false)
      expect(hasDiscount({ price: 1199, discounted_price: 1500 })).toBe(false)
    })

    it('is false when either price is missing, zero or the item itself is absent', () => {
      expect(hasDiscount({ price: 1199 })).toBe(false)
      expect(hasDiscount({ discounted_price: 1000 })).toBe(false)
      expect(hasDiscount({ price: 0, discounted_price: 0 })).toBe(false)
      expect(hasDiscount(null)).toBe(false)
      expect(hasDiscount(undefined)).toBe(false)
    })
  })

  describe('effectivePrice', () => {
    it('returns the negotiated price when one is active', () => {
      expect(effectivePrice({ price: 1199, discounted_price: 1000 })).toBe(1000)
    })

    it('falls back to the listed price otherwise', () => {
      expect(effectivePrice({ price: 1199 })).toBe(1199)
      expect(effectivePrice({ price: 1199, discounted_price: 1199 })).toBe(1199)
      expect(effectivePrice(null)).toBe(0)
    })
  })

  describe('discountPercent', () => {
    it('rounds the saving to a whole percentage', () => {
      expect(discountPercent({ price: 1199, discounted_price: 1000 })).toBe(17)
      expect(discountPercent({ price: 200, discounted_price: 150 })).toBe(25)
      expect(discountPercent({ price: 100, discounted_price: 1 })).toBe(99)
    })

    it('is 0 when there is no active discount', () => {
      expect(discountPercent({ price: 1199 })).toBe(0)
      expect(discountPercent({ price: 1199, discounted_price: 1199 })).toBe(0)
      expect(discountPercent(null)).toBe(0)
    })
  })

  describe('parsePriceFromLabel', () => {
    it('pulls the amount out of the phrasings the agent actually emits', () => {
      expect(parsePriceFromLabel('Pay RM1000 Now')).toBe(1000)
      expect(parsePriceFromLabel('Pay RM71.50 Now')).toBe(71.5)
      expect(parsePriceFromLabel('Pay RM 1,199.50 Now')).toBe(1199.5)
      expect(parsePriceFromLabel('Bayar RM450 sekarang')).toBe(450)
      expect(parsePriceFromLabel('pay rm25 now')).toBe(25)
    })

    it('returns null when the label carries no amount', () => {
      expect(parsePriceFromLabel('Complete checkout')).toBeNull()
      expect(parsePriceFromLabel('RM')).toBeNull()
      expect(parsePriceFromLabel('')).toBeNull()
      expect(parsePriceFromLabel(undefined)).toBeNull()
      expect(parsePriceFromLabel(null)).toBeNull()
    })
  })

  describe('formatPrice', () => {
    it('renders two decimals with the RM prefix', () => {
      expect(formatPrice(1000)).toBe('RM 1000.00')
      expect(formatPrice(45.5)).toBe('RM 45.50')
    })

    it('treats a missing amount as zero', () => {
      expect(formatPrice(undefined)).toBe('RM 0.00')
      expect(formatPrice(null)).toBe('RM 0.00')
    })
  })
})
