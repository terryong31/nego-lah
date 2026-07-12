import { afterEach, describe, expect, it } from 'vitest'
import { mockComponent, mountSuspended } from '@nuxt/test-utils/runtime'
import { nextTick } from 'vue'
import ChatsPage from '~/pages/_console/chats.vue'
import ItemsPage from '~/pages/_console/items.vue'
import OrdersPage from '~/pages/_console/orders.vue'
import UsersPage from '~/pages/_console/users.vue'

// These four pages are thin wrappers around their corresponding
// components/admin/Admin*.vue components (which already have their own
// dedicated test files under tests/components/admin/). Stub the admin
// components out here so we only exercise the wrapper page's own logic:
// the SEO title/meta it sets and the fact that it renders the right child.
mockComponent('AdminChats', {
  template: '<div class="admin-chats-stub" />'
})
mockComponent('AdminItems', {
  template: '<div class="admin-items-stub" />'
})
mockComponent('AdminOrders', {
  template: '<div class="admin-orders-stub" />'
})
mockComponent('AdminUsers', {
  template: '<div class="admin-users-stub" />'
})

let activeWrapper: Awaited<ReturnType<typeof mountSuspended>> | undefined

afterEach(() => {
  activeWrapper?.unmount()
  activeWrapper = undefined
})

async function mountPage(component: Parameters<typeof mountSuspended>[0]) {
  activeWrapper = await mountSuspended(component)
  await nextTick()
  // unhead patches the real DOM (document.title, <meta>, ...) via a
  // `setTimeout(fn, 0)`-debounced render, not synchronously and not just a
  // microtask — a plain `nextTick()` isn't enough to observe it.
  await new Promise(resolve => setTimeout(resolve, 0))
  return activeWrapper
}

describe('pages/_console/chats.vue', () => {
  it('sets the "Chats · Admin" SEO title and noindex robots meta', async () => {
    await mountPage(ChatsPage)

    expect(document.title).toBe('Chats · Admin')
    const robots = document.querySelector('meta[name="robots"]')
    expect(robots?.getAttribute('content')).toBe('noindex, nofollow')
  })

  it('renders the "Chats" navbar title and the stubbed AdminChats component', async () => {
    const wrapper = await mountPage(ChatsPage)

    expect(wrapper.text()).toContain('Chats')
    expect(wrapper.find('.admin-chats-stub').exists()).toBe(true)
    expect(wrapper.find('.admin-items-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-orders-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-users-stub').exists()).toBe(false)
  })
})

describe('pages/_console/items.vue', () => {
  it('sets the "Items · Admin" SEO title and noindex robots meta', async () => {
    await mountPage(ItemsPage)

    expect(document.title).toBe('Items · Admin')
    const robots = document.querySelector('meta[name="robots"]')
    expect(robots?.getAttribute('content')).toBe('noindex, nofollow')
  })

  it('renders the "Items" navbar title and the stubbed AdminItems component', async () => {
    const wrapper = await mountPage(ItemsPage)

    expect(wrapper.text()).toContain('Items')
    expect(wrapper.find('.admin-items-stub').exists()).toBe(true)
    expect(wrapper.find('.admin-chats-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-orders-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-users-stub').exists()).toBe(false)
  })
})

describe('pages/_console/orders.vue', () => {
  it('sets the "Orders · Admin" SEO title and noindex robots meta', async () => {
    await mountPage(OrdersPage)

    expect(document.title).toBe('Orders · Admin')
    const robots = document.querySelector('meta[name="robots"]')
    expect(robots?.getAttribute('content')).toBe('noindex, nofollow')
  })

  it('renders the "Orders" navbar title and the stubbed AdminOrders component', async () => {
    const wrapper = await mountPage(OrdersPage)

    expect(wrapper.text()).toContain('Orders')
    expect(wrapper.find('.admin-orders-stub').exists()).toBe(true)
    expect(wrapper.find('.admin-chats-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-items-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-users-stub').exists()).toBe(false)
  })
})

describe('pages/_console/users.vue', () => {
  it('sets the "Users · Admin" SEO title and noindex robots meta', async () => {
    await mountPage(UsersPage)

    expect(document.title).toBe('Users · Admin')
    const robots = document.querySelector('meta[name="robots"]')
    expect(robots?.getAttribute('content')).toBe('noindex, nofollow')
  })

  it('renders the "Users" navbar title and the stubbed AdminUsers component', async () => {
    const wrapper = await mountPage(UsersPage)

    expect(wrapper.text()).toContain('Users')
    expect(wrapper.find('.admin-users-stub').exists()).toBe(true)
    expect(wrapper.find('.admin-chats-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-items-stub').exists()).toBe(false)
    expect(wrapper.find('.admin-orders-stub').exists()).toBe(false)
  })
})
