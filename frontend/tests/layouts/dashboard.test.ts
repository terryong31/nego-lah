import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountSuspended, mockNuxtImport } from '@nuxt/test-utils/runtime'
import DashboardLayout from '~/layouts/dashboard.vue'

const { callMock, toastAddMock, navigateToMock } = vi.hoisted(() => ({
  callMock: vi.fn(),
  toastAddMock: vi.fn(),
  navigateToMock: vi.fn()
}))

mockNuxtImport('useAdminApi', () => () => ({ call: callMock }))
mockNuxtImport('useToast', () => () => ({ add: toastAddMock }))
mockNuxtImport('navigateTo', () => navigateToMock)

describe('layouts/dashboard.vue', () => {
  afterEach(() => {
    callMock.mockReset()
    toastAddMock.mockReset()
    navigateToMock.mockReset()
  })

  it('renders all sidebar nav links with correct labels and targets', async () => {
    callMock.mockResolvedValue({})
    const wrapper = await mountSuspended(DashboardLayout, {
      slots: { default: () => 'Page content' }
    })

    const text = wrapper.text()
    expect(text).toContain('Dashboard')
    expect(text).toContain('Users')
    expect(text).toContain('Items')
    expect(text).toContain('Orders')
    expect(text).toContain('Chats')
    expect(text).toContain('Admin Console')
    expect(text).toContain('Page content')

    const hrefs = wrapper.findAll('a').map(a => a.attributes('href'))
    expect(hrefs).toContain('/_console')
    expect(hrefs).toContain('/_console/users')
    expect(hrefs).toContain('/_console/items')
    expect(hrefs).toContain('/_console/orders')
    expect(hrefs).toContain('/_console/chats')
  })

  it('renders the slot content passed to the layout', async () => {
    const wrapper = await mountSuspended(DashboardLayout, {
      slots: { default: () => 'Hello from a page' }
    })

    expect(wrapper.text()).toContain('Hello from a page')
  })

  it('logout(): on success calls the admin logout endpoint, shows a success toast, and redirects to the console login', async () => {
    callMock.mockResolvedValueOnce({})
    const wrapper = await mountSuspended(DashboardLayout, {
      slots: { default: () => 'content' }
    })

    interface DropdownItemLike {
      label?: string
      onSelect?: () => void | Promise<void>
    }

    const vm = wrapper.vm as unknown as { footerDropdownItems: DropdownItemLike[][] }
    const items = vm.footerDropdownItems
    const logoutItem = items.flat().find(i => i.label === 'Logout')
    expect(logoutItem).toBeTruthy()

    await logoutItem?.onSelect?.()
    await flushPromises()

    expect(callMock).toHaveBeenCalledTimes(1)
    expect(callMock).toHaveBeenCalledWith('/auth/logout', { method: 'POST' })
    expect(toastAddMock).toHaveBeenCalledTimes(1)
    expect(toastAddMock).toHaveBeenCalledWith({ title: 'Signed out', color: 'success' })
    expect(navigateToMock).toHaveBeenCalledTimes(1)
    expect(navigateToMock).toHaveBeenCalledWith('/_console/login')
  })

  it('logout(): clears locally regardless — still toasts and redirects even when the API call rejects', async () => {
    callMock.mockRejectedValueOnce(new Error('network down'))
    const wrapper = await mountSuspended(DashboardLayout, {
      slots: { default: () => 'content' }
    })

    interface DropdownItemLike {
      label?: string
      onSelect?: () => void | Promise<void>
    }

    const vm = wrapper.vm as unknown as { footerDropdownItems: DropdownItemLike[][] }
    const items = vm.footerDropdownItems
    const logoutItem = items.flat().find(i => i.label === 'Logout')
    expect(logoutItem).toBeTruthy()

    await logoutItem?.onSelect?.()
    await flushPromises()

    expect(callMock).toHaveBeenCalledTimes(1)
    expect(callMock).toHaveBeenCalledWith('/auth/logout', { method: 'POST' })
    // error from `call` is swallowed - logout still "succeeds" locally
    expect(toastAddMock).toHaveBeenCalledTimes(1)
    expect(toastAddMock).toHaveBeenCalledWith({ title: 'Signed out', color: 'success' })
    expect(navigateToMock).toHaveBeenCalledTimes(1)
    expect(navigateToMock).toHaveBeenCalledWith('/_console/login')
  })
})
