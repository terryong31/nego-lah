export interface PricedItem {
  price?: number
  discounted_price?: number
}

/**
 * The price the buyer actually pays: the negotiated offer when one is active
 * and genuinely lower than the listing, otherwise the listed price.
 */
export function effectivePrice(item?: PricedItem | null): number {
  const listed = item?.price ?? 0
  const discounted = item?.discounted_price
  return hasDiscount(item) ? discounted! : listed
}

/** True when the item carries an active negotiated price below the listed one. */
export function hasDiscount(item?: PricedItem | null): boolean {
  const listed = item?.price
  const discounted = item?.discounted_price
  return !!discounted && !!listed && discounted < listed
}

/**
 * How much the negotiation shaved off, as a rounded whole percentage
 * (e.g. 1199 -> 1000 gives 17). Returns 0 when there's no active discount.
 */
export function discountPercent(item?: PricedItem | null): number {
  if (!hasDiscount(item)) return 0
  const listed = item!.price!
  return Math.round(((listed - item!.discounted_price!) / listed) * 100)
}

/** Formats an amount as the storefront's currency string, e.g. "RM 1000.00". */
export function formatPrice(amount?: number | null): string {
  return `RM ${(amount ?? 0).toFixed(2)}`
}

/**
 * Pulls the ringgit amount out of an agent-authored payment link label, e.g.
 * "Pay RM1,199.50 Now" -> 1199.5. Returns null when the label carries no
 * recognisable amount, so callers can fall back to the raw text.
 */
export function parsePriceFromLabel(label?: string | null): number | null {
  if (!label) return null
  const match = label.match(/RM\s*([\d,]+(?:\.\d{1,2})?)/i)
  if (!match?.[1]) return null
  const amount = Number.parseFloat(match[1].replace(/,/g, ''))
  return Number.isFinite(amount) ? amount : null
}
