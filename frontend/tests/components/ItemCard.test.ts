import { describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import ItemCard from '~/components/ItemCard.vue'

const { navigateToMock } = vi.hoisted(() => ({
  navigateToMock: vi.fn()
}))

mockNuxtImport('navigateTo', () => navigateToMock)

const baseItem = {
  item_id: 'item-1',
  name: 'Vintage Camera',
  description: 'A nice old camera',
  condition: 'Used - Good',
  images: '["/img/a.jpg", "/img/b.jpg"]',
  price: 123.4,
  min_price: 100,
  status: 'available'
}

describe('components/ItemCard.vue', () => {
  it('renders the skeleton when loading is true, even if an item is provided', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { loading: true, item: baseItem }
    })

    expect(wrapper.findComponent({ name: 'USkeleton' }).exists()).toBe(true)
    // The real card content should not be rendered while loading.
    expect(wrapper.text()).not.toContain(baseItem.name)
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('renders nothing when there is no item and not loading', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { loading: false }
    })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'USkeleton' }).exists()).toBe(false)
    expect(wrapper.text().trim()).toBe('')
  })

  it('uses the first element of a valid JSON array of images', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: '["/img/a.jpg", "/img/b.jpg"]' } }
    })

    expect(wrapper.find('img').attributes('src')).toBe('/img/a.jpg')
  })

  it('falls back to comma-splitting when images is not valid JSON', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: '/img/c.jpg, /img/d.jpg' } }
    })

    expect(wrapper.find('img').attributes('src')).toBe('/img/c.jpg')
  })

  it('uses the raw string as an ultimate fallback when it is a bare string with no commas', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: '/img/single.jpg' } }
    })

    expect(wrapper.find('img').attributes('src')).toBe('/img/single.jpg')
  })

  it('uses the raw images string as the ultimate fallback when it parses as valid JSON but is not a non-empty array', async () => {
    // JSON.parse succeeds (so the catch/comma-split branch never runs) but the
    // parsed value isn't a non-empty array, so neither `return parsed[0]` nor
    // the comma-split `return` fire, falling through to `return item.images`.
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: '{"foo":"bar"}' } }
    })

    expect(wrapper.find('img').attributes('src')).toBe('{"foo":"bar"}')
  })

  it('uses the raw images string as the ultimate fallback when comma-splitting yields an empty first segment', async () => {
    // Not valid JSON, so we land in the catch block; splitting on ',' yields
    // an empty first segment, so the comma-split `return` doesn't fire either.
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: ',/img/e.jpg' } }
    })

    expect(wrapper.find('img').attributes('src')).toBe(',/img/e.jpg')
  })

  it('falls back to /placeholder.png when the item has no images', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: '' } }
    })

    expect(wrapper.find('img').attributes('src')).toBe('/placeholder.png')
  })

  it('falls back to /placeholder.png when there is no item at all but loading is false and item undefined is passed explicitly', async () => {
    // imageUrl logic is only reachable when item exists (v-else-if="item"), but
    // guard against a falsy-images item still resolving the placeholder branch.
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, images: undefined as unknown as string } }
    })

    expect(wrapper.find('img').attributes('src')).toBe('/placeholder.png')
  })

  it('shows the "Sold" badge when item.status is sold', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, status: 'sold' } }
    })

    expect(wrapper.text()).toContain('Sold')
  })

  it('does not show the "Sold" badge when item.status is available', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, status: 'available' } }
    })

    expect(wrapper.text()).not.toContain('Sold')
  })

  it('formats the price to 2 decimal places when present', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, price: 99.5 } }
    })

    expect(wrapper.text()).toContain('RM 99.50')
  })

  it('defaults the price to 0.00 when item.price is undefined', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: { item: { ...baseItem, price: undefined } }
    })

    expect(wrapper.text()).toContain('RM 0.00')
  })

  it('renders the item name and condition', async () => {
    const wrapper = await mountSuspended(ItemCard, { props: { item: baseItem } })

    expect(wrapper.text()).toContain(baseItem.name)
    expect(wrapper.text()).toContain(baseItem.condition)
  })

  it('renders localized title and condition when translation is available for the current locale', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: {
        item: {
          ...baseItem,
          translations: {
            en: { name: 'Localized Camera', condition: 'Mint' }
          }
        }
      }
    })

    expect(wrapper.text()).toContain('Localized Camera')
    expect(wrapper.text()).toContain('Mint')
  })

  it('falls back to item.name and item.condition when no translation for current locale exists', async () => {
    const wrapper = await mountSuspended(ItemCard, {
      props: {
        item: {
          ...baseItem,
          translations: {
            zh: { name: '中文相机', condition: '全新' }
          }
        }
      }
    })

    expect(wrapper.text()).toContain(baseItem.name)
    expect(wrapper.text()).toContain(baseItem.condition)
  })

  it('navigates to the item detail page when the card is clicked', async () => {
    navigateToMock.mockClear()

    const wrapper = await mountSuspended(ItemCard, { props: { item: baseItem } })

    await wrapper.find('.group.cursor-pointer').trigger('click')

    expect(navigateToMock).toHaveBeenCalledWith(`/items/${baseItem.item_id}`)
  })

  // SPEC-031: the card's own skeleton defines the intended design — one padding
  // on the whole card, with a rounded image inset inside it. The loaded card has
  // to match, or the grid reflows the moment data arrives.
  describe('padding parity (SPEC-031)', () => {
    function padding(classes: string) {
      return classes.split(/\s+/).filter(c => /^(sm:)?p-/.test(c)).sort().join(' ')
    }

    it('gives the body and the footer the same padding', async () => {
      const wrapper = await mountSuspended(ItemCard, { props: { item: baseItem } })
      const ui = wrapper.findComponent({ name: 'UCard' }).props('ui') as Record<string, string>

      expect(padding(ui.body)).not.toBe('')
      expect(padding(ui.body)).toBe(padding(ui.footer))
    })

    it('does not let the title/condition wrapper set its own inset', async () => {
      const wrapper = await mountSuspended(ItemCard, { props: { item: baseItem } })

      const heading = wrapper.find('h3')
      const textWrapper = heading.element.parentElement!
      expect(padding(textWrapper.className)).toBe('')
    })

    it('rounds the image the same way the skeleton does', async () => {
      const wrapper = await mountSuspended(ItemCard, { props: { item: baseItem } })

      const imageWrapper = wrapper.find('img').element.parentElement!
      expect(imageWrapper.className).toContain('rounded-lg')
    })
  })

  describe('sold treatment (SPEC-031)', () => {
    it('greys out the image of a sold item', async () => {
      const wrapper = await mountSuspended(ItemCard, {
        props: { item: { ...baseItem, status: 'sold' } }
      })

      expect(wrapper.find('img').classes()).toContain('grayscale')
    })

    it('leaves an available item in full colour', async () => {
      const wrapper = await mountSuspended(ItemCard, {
        props: { item: { ...baseItem, status: 'available' } }
      })

      expect(wrapper.find('img').classes()).not.toContain('grayscale')
    })

    it('renders the Sold badge larger than the previous sm', async () => {
      const wrapper = await mountSuspended(ItemCard, {
        props: { item: { ...baseItem, status: 'sold' } }
      })

      const badge = wrapper.findComponent({ name: 'UBadge' })
      expect(badge.exists()).toBe(true)
      expect(['md', 'lg', 'xl']).toContain(badge.props('size'))
    })
  })

  it('renders discounted_price and strikethrough original price when discounted', async () => {
    const discountedItem = {
      ...baseItem,
      price: 150,
      discounted_price: 120
    }
    const wrapper = await mountSuspended(ItemCard, { props: { item: discountedItem } })

    expect(wrapper.text()).toContain('RM 120.00')
    expect(wrapper.text()).toContain('RM 150.00')
    expect(wrapper.find('.line-through').text()).toContain('RM 150.00')
  })
})
