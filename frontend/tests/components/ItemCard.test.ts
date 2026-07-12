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

  it('navigates to the item detail page when the card is clicked', async () => {
    navigateToMock.mockClear()

    const wrapper = await mountSuspended(ItemCard, { props: { item: baseItem } })

    await wrapper.find('.group.cursor-pointer').trigger('click')

    expect(navigateToMock).toHaveBeenCalledWith(`/items/${baseItem.item_id}`)
  })
})
