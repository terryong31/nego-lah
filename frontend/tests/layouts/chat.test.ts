import { describe, expect, it } from 'vitest'
import { mockComponent, mountSuspended } from '@nuxt/test-utils/runtime'
import ChatLayout from '~/layouts/chat.vue'

// Isolate the layout from AppHeader's real implementation (Supabase user/client,
// router, toast, dropdown items) — this test only cares about the layout shell.
mockComponent('AppHeader', () => ({
  template: '<header data-testid="app-header">Header Stub</header>'
}))

describe('layouts/chat.vue', () => {
  it('renders AppHeader above the slot content', async () => {
    const wrapper = await mountSuspended(ChatLayout, {
      slots: {
        default: () => 'Chat content'
      }
    })

    const header = wrapper.find('[data-testid="app-header"]')
    expect(header.exists()).toBe(true)
    expect(header.text()).toBe('Header Stub')
    expect(wrapper.text()).toContain('Chat content')

    // Header must precede the slot content in DOM order.
    const html = wrapper.html()
    expect(html.indexOf('app-header')).toBeLessThan(html.indexOf('Chat content'))
  })

  it('wraps content in a full-height flex column container', async () => {
    const wrapper = await mountSuspended(ChatLayout, {
      slots: {
        default: () => 'Chat content'
      }
    })

    const root = wrapper.find('div.flex.flex-col.h-screen')
    expect(root.exists()).toBe(true)
    // Both AppHeader and the slot content should live inside this container.
    expect(root.text()).toContain('Header Stub')
    expect(root.text()).toContain('Chat content')
  })

  it('renders arbitrary slot markup passed by the page', async () => {
    const wrapper = await mountSuspended(ChatLayout, {
      slots: {
        default: () => '<p class="msg">Hello from a page</p>'
      }
    })

    expect(wrapper.html()).toContain('Hello from a page')
  })

  it('renders without slot content without throwing', async () => {
    const wrapper = await mountSuspended(ChatLayout)

    expect(wrapper.find('[data-testid="app-header"]').exists()).toBe(true)
    expect(wrapper.find('div.flex.flex-col.h-screen').exists()).toBe(true)
  })
})
