export interface ItemTranslation {
  name?: string
  description?: string
  condition?: string
}

export interface TranslatableItem {
  name?: string
  description?: string
  condition?: string
  translations?: Record<string, ItemTranslation>
}

/**
 * The item's copy in the reader's language, falling back to the seller's
 * original wording when that locale hasn't been translated yet.
 *
 * Listings are translated on ingest (SPEC-008), so `translations` is keyed by
 * locale code and may be missing entirely for older rows.
 */
export function localizedItemField(
  item: TranslatableItem | null | undefined,
  locale: string,
  field: keyof ItemTranslation
): string {
  if (!item) return ''
  return item.translations?.[locale]?.[field] || item[field] || ''
}
