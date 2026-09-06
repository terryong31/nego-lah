import { describe, expect, it } from 'vitest'
import { extractTrilingualData } from '~/utils/trilingual'

// The AI drafts a listing in all three locales and hands it back as JSON. It
// usually obliges, but it also fences the JSON in markdown, prefixes it with
// prose, or leaves an unescaped quote inside a description — so this parser
// exists precisely for the cases a bare JSON.parse loses. It was buried inside
// AdminItems.vue and only reachable by mounting the component; SPEC-037 lifted
// it out so the salvage paths can be tested for what they are.

describe('utils/trilingual: extractTrilingualData', () => {
  describe('rejects unusable input', () => {
    it.each([
      ['undefined', undefined],
      ['empty string', ''],
      ['prose with no object', 'I could not identify this item.'],
      ['an opening brace only', 'here you go: {'],
      ['a closing brace before the opening one', '} {']
    ])('returns null for %s', (_label, input) => {
      expect(extractTrilingualData(input as string | undefined)).toBeNull()
    })

    it('returns null for valid JSON that carries no language keys', () => {
      expect(extractTrilingualData('{"name": "Chair", "price": 40}')).toBeNull()
    })
  })

  describe('clean JSON', () => {
    it('parses a well-formed trilingual object', () => {
      const raw = JSON.stringify({
        en: { name: 'Chair', description: 'A comfy chair', condition: 'Good' },
        ms: { name: 'Kerusi', description: 'Kerusi selesa', condition: 'Baik' },
        zh: { name: '椅子', description: '舒适的椅子', condition: '良好' }
      })

      expect(extractTrilingualData(raw)?.ms?.name).toBe('Kerusi')
      expect(extractTrilingualData(raw)?.zh?.description).toBe('舒适的椅子')
    })

    it('ignores prose and markdown fencing around the object', () => {
      const raw = 'Sure! Here is the listing:\n```json\n'
        + '{"en": {"name": "Lamp", "description": "Brass lamp", "condition": "Fair"}}\n'
        + '```\nLet me know if you want changes.'

      expect(extractTrilingualData(raw)).toEqual({
        en: { name: 'Lamp', description: 'Brass lamp', condition: 'Fair' }
      })
    })

    it('accepts a partial draft with only some locales filled in', () => {
      const result = extractTrilingualData('{"en": {"name": "Desk"}}')
      expect(result).toEqual({ en: { name: 'Desk' } })
    })
  })

  describe('regex salvage for malformed JSON', () => {
    it('recovers each language block when a stray quote breaks the parse', () => {
      // The unescaped quote around 12" is what makes JSON.parse throw.
      const raw = '{"en": {"name": "12" Skillet", "description": "Cast iron", "condition": "Good"},'
        + ' "ms": {"name": "Kuali", "description": "Besi tuang", "condition": "Baik"}}'

      const result = extractTrilingualData(raw)

      expect(result).not.toBeNull()
      expect(result?.ms).toEqual({
        name: 'Kuali',
        description: 'Besi tuang',
        condition: 'Baik'
      })
    })

    it('unescapes quotes and newlines inside a salvaged block', () => {
      const raw = '{"en": {"name": "A \\"rare\\" find", "description": "Line one\\nLine two", "condition": "x" "},'
        + ' "zh": {"name": "宝贝", "description": "描述", "condition": "良好"}}'

      const result = extractTrilingualData(raw)

      expect(result?.en?.name).toBe('A "rare" find')
      expect(result?.en?.description).toBe('Line one\nLine two')
    })

    it('fills missing fields with empty strings rather than dropping the block', () => {
      // `ms` is what breaks the parse; `en` is well-formed but sparse.
      const raw = '{"en": {"name": "Bare"},'
        + ' "ms": {"name": "Kosong", "description": "un"escaped", "condition": "c"}}'

      const result = extractTrilingualData(raw)

      expect(result?.en).toEqual({ name: 'Bare', description: '', condition: '' })
    })

    it('returns null when the salvage finds no language block either', () => {
      expect(extractTrilingualData('{"totally": "unrelated" "}')).toBeNull()
    })
  })
})
