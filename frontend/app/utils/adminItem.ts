import type { ItemTranslation } from './item'

/**
 * A listing as the ADMIN console sees it.
 *
 * Deliberately distinct from the storefront's item shape: this one carries
 * `min_price`, the negotiation floor. The seller sets it, so the seller's
 * console shows it — but it never appears in a public response (SPEC-036), and
 * the storefront types must not grow the field back.
 */
export interface AdminItem {
  id: string
  name: string
  description: string
  condition: string
  price: number
  min_price: number | null
  image_path: string | null
  status: string
  created_at: string
  translations?: Record<string, ItemTranslation>
}

/**
 * The listing's photos, in display order.
 *
 * `image_path` is a `{storage filename: public url}` map whose insertion order
 * IS the display order, so the first value is the thumbnail.
 */
export function itemImageUrls(item: Pick<AdminItem, 'image_path'>): string[] {
  if (!item.image_path) return []
  try {
    const map = JSON.parse(item.image_path)
    if (!map || typeof map !== 'object') return []
    return (Object.values(map) as string[]).filter(url => typeof url === 'string')
  } catch {
    return []
  }
}

export function itemThumbnail(item: Pick<AdminItem, 'image_path'>): string | undefined {
  return itemImageUrls(item)[0]
}
