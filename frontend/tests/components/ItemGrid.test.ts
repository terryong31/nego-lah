import { describe, expect, it } from 'vitest'
import { mountSuspended, mockComponent } from '@nuxt/test-utils/runtime'
import ItemGrid from '~/components/ItemGrid.vue'

mockComponent('ItemCard', {
  props: {
    item: { type: Object, default: undefined },
    loading: { type: Boolean, default: false }
  },
  template: '<div class="item-card-stub" :data-loading="loading" :data-item-id="item?.item_id" />'
})

interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string
  price?: number
  min_price?: number
  status?: string
}

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    item_id: 'item-1',
    name: 'Test Item',
    description: 'A test item',
    condition: 'new',
    images: '[]',
    ...overrides
  }
}

describe('components/ItemGrid.vue', () => {
  it('renders 8 skeleton ItemCards when loading is true', async () => {
    const wrapper = await mountSuspended(ItemGrid, {
      props: {
        items: [],
        loading: true
      }
    })

    const cards = wrapper.findAll('.item-card-stub')
    expect(cards).toHaveLength(8)
    cards.forEach((card) => {
      expect(card.attributes('data-loading')).toBe('true')
    })

    // Empty state and grid list should not be rendered while loading
    expect(wrapper.text()).not.toContain('No Items Found')
  })

  it('renders 8 skeleton ItemCards when loading is true even if items are provided', async () => {
    const wrapper = await mountSuspended(ItemGrid, {
      props: {
        items: [makeItem()],
        loading: true
      }
    })

    expect(wrapper.findAll('.item-card-stub')).toHaveLength(8)
  })

  it('renders the empty state when items is an empty array and not loading', async () => {
    const wrapper = await mountSuspended(ItemGrid, {
      props: {
        items: [],
        loading: false
      }
    })

    expect(wrapper.find('h3').text()).toBe('No Items Found')
    expect(wrapper.text()).toContain('Terry Ong has not uploaded anything for sale yet')
    expect(wrapper.findAll('.item-card-stub')).toHaveLength(0)
  })

  it('renders the empty state when loading prop is omitted and items is empty', async () => {
    const wrapper = await mountSuspended(ItemGrid, {
      props: {
        items: []
      }
    })

    expect(wrapper.find('h3').text()).toBe('No Items Found')
  })

  it('renders one ItemCard per item, keyed by item_id, when items is populated', async () => {
    const items = [
      makeItem({ item_id: 'a1', name: 'Item A' }),
      makeItem({ item_id: 'b2', name: 'Item B' }),
      makeItem({ item_id: 'c3', name: 'Item C' })
    ]

    const wrapper = await mountSuspended(ItemGrid, {
      props: {
        items,
        loading: false
      }
    })

    const cards = wrapper.findAll('.item-card-stub')
    expect(cards).toHaveLength(3)
    expect(cards.map(c => c.attributes('data-item-id'))).toEqual(['a1', 'b2', 'c3'])
    cards.forEach((card) => {
      expect(card.attributes('data-loading')).toBe('false')
    })
    expect(wrapper.text()).not.toContain('No Items Found')
  })
})
