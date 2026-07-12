import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'

// A minimal chainable fake standing in for a Supabase RealtimeChannel: records
// the handlers registered via `.on(...)` and the callback passed to
// `.subscribe(...)` so tests can trigger them manually.
function createFakeChannel() {
  const handlers: Record<string, (arg: unknown) => void> = {}
  const fake: {
    on: ReturnType<typeof vi.fn>
    subscribe: ReturnType<typeof vi.fn>
    send: ReturnType<typeof vi.fn>
    handlers: Record<string, (arg: unknown) => void>
    subscribeCb?: (status: string) => void
  } = {
    on: vi.fn((_type: string, filter: { event: string }, cb: (arg: unknown) => void) => {
      handlers[filter.event] = cb
      return fake
    }),
    subscribe: vi.fn((cb: (status: string) => void) => {
      fake.subscribeCb = cb
      return fake
    }),
    send: vi.fn(),
    handlers
  }
  return fake
}

let currentChannel: ReturnType<typeof createFakeChannel>

const fakeSupabase = {
  channel: vi.fn(),
  removeChannel: vi.fn(),
  realtime: { setAuth: vi.fn() }
}

mockNuxtImport('useSupabaseClient', () => () => fakeSupabase)

const Host = defineComponent({
  setup() {
    return useTypingChannel()
  },
  template: '<div />'
})

describe('composables/useTypingChannel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fakeSupabase.channel.mockReset()
    fakeSupabase.removeChannel.mockReset()
    fakeSupabase.realtime.setAuth.mockReset()
    fakeSupabase.channel.mockImplementation(() => {
      currentChannel = createFakeChannel()
      return currentChannel
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('creates a channel named after the conversation with broadcast self disabled', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })

    expect(fakeSupabase.channel).toHaveBeenCalledWith('chat:conv1', {
      config: { broadcast: { self: false } }
    })
    expect(currentChannel.on).toHaveBeenCalledWith('broadcast', { event: 'typing' }, expect.any(Function))
    expect(currentChannel.on).toHaveBeenCalledWith('broadcast', { event: 'new_message' }, expect.any(Function))
    expect(currentChannel.subscribe).toHaveBeenCalledWith(expect.any(Function))
  })

  it('sets remoteTyping on a matching broadcast and clears it 3000ms after the last one', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    currentChannel.subscribeCb?.('SUBSCRIBED')

    currentChannel.handlers.typing({ payload: { role: 'seller' } })
    expect(wrapper.vm.remoteTyping).toBe(true)

    vi.advanceTimersByTime(2999)
    expect(wrapper.vm.remoteTyping).toBe(true)

    vi.advanceTimersByTime(1)
    expect(wrapper.vm.remoteTyping).toBe(false)
  })

  it('restarts the 3000ms clear window on each new matching broadcast', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    currentChannel.subscribeCb?.('SUBSCRIBED')

    currentChannel.handlers.typing({ payload: { role: 'seller' } })
    vi.advanceTimersByTime(2000)
    expect(wrapper.vm.remoteTyping).toBe(true)

    // A fresh broadcast before the first timer fires should push the deadline out.
    currentChannel.handlers.typing({ payload: { role: 'seller' } })
    vi.advanceTimersByTime(2000)
    expect(wrapper.vm.remoteTyping).toBe(true)

    vi.advanceTimersByTime(1000)
    expect(wrapper.vm.remoteTyping).toBe(false)
  })

  it('ignores broadcasts whose role does not match listenFor', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    currentChannel.subscribeCb?.('SUBSCRIBED')

    // "customer" is our own outgoing role, not the one we listen for.
    currentChannel.handlers.typing({ payload: { role: 'customer' } })
    expect(wrapper.vm.remoteTyping).toBe(false)

    vi.advanceTimersByTime(3000)
    expect(wrapper.vm.remoteTyping).toBe(false)
  })

  it('ignores broadcasts with no role at all', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    currentChannel.subscribeCb?.('SUBSCRIBED')

    currentChannel.handlers.typing({ payload: {} })
    expect(wrapper.vm.remoteTyping).toBe(false)
  })

  it('invokes onMessage for new_message broadcasts and tolerates a missing callback', async () => {
    const onMessage = vi.fn()
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer', onMessage })
    currentChannel.subscribeCb?.('SUBSCRIBED')

    currentChannel.handlers.new_message({ payload: { text: 'hi' } })
    expect(onMessage).toHaveBeenCalledWith({ text: 'hi' })

    // Re-join without an onMessage handler — must not throw when a message arrives.
    wrapper.vm.join('conv2', { listenFor: 'seller', sendAs: 'customer' })
    expect(() => currentChannel.handlers.new_message({ payload: { text: 'again' } })).not.toThrow()
  })

  it('does not send a ping until the channel is ready (SUBSCRIBED)', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })

    wrapper.vm.ping()
    expect(currentChannel.send).not.toHaveBeenCalled()

    currentChannel.subscribeCb?.('SUBSCRIBED')
    wrapper.vm.ping()
    expect(currentChannel.send).toHaveBeenCalledTimes(1)
    expect(currentChannel.send).toHaveBeenCalledWith({
      type: 'broadcast',
      event: 'typing',
      payload: { role: 'customer' }
    })
  })

  it('does not become ready (and does not send) on CHANNEL_ERROR / TIMED_OUT, and warns', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })

    currentChannel.subscribeCb?.('CHANNEL_ERROR')
    wrapper.vm.ping()
    expect(currentChannel.send).not.toHaveBeenCalled()
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('CHANNEL_ERROR'))

    warnSpy.mockClear()
    currentChannel.subscribeCb?.('TIMED_OUT')
    wrapper.vm.ping()
    expect(currentChannel.send).not.toHaveBeenCalled()
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('TIMED_OUT'))
  })

  it('throttles ping() to once per 1500ms', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    currentChannel.subscribeCb?.('SUBSCRIBED')

    wrapper.vm.ping()
    expect(currentChannel.send).toHaveBeenCalledTimes(1)

    // Immediate follow-up pings within the window are dropped.
    vi.advanceTimersByTime(1000)
    wrapper.vm.ping()
    expect(currentChannel.send).toHaveBeenCalledTimes(1)

    // Once the throttle window elapses, the next ping goes through.
    vi.advanceTimersByTime(500)
    wrapper.vm.ping()
    expect(currentChannel.send).toHaveBeenCalledTimes(2)
  })

  it('setAuth is called with the access token when provided, and swallows errors', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer', accessToken: 'tok-123' })
    expect(fakeSupabase.realtime.setAuth).toHaveBeenCalledWith('tok-123')

    fakeSupabase.realtime.setAuth.mockImplementationOnce(() => {
      throw new Error('boom')
    })
    expect(() =>
      wrapper.vm.join('conv2', { listenFor: 'seller', sendAs: 'customer', accessToken: 'tok-456' })
    ).not.toThrow()
  })

  it('does not call setAuth when no accessToken is supplied (anon admin side)', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'customer', sendAs: 'seller' })
    expect(fakeSupabase.realtime.setAuth).not.toHaveBeenCalled()
  })

  it('join() calls leave() first: re-joining tears down the previous channel and resets state', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    const firstChannel = currentChannel
    firstChannel.subscribeCb?.('SUBSCRIBED')
    firstChannel.handlers.typing({ payload: { role: 'seller' } })
    expect(wrapper.vm.remoteTyping).toBe(true)

    wrapper.vm.join('conv2', { listenFor: 'seller', sendAs: 'customer' })

    expect(fakeSupabase.removeChannel).toHaveBeenCalledWith(firstChannel)
    expect(wrapper.vm.remoteTyping).toBe(false)
    expect(fakeSupabase.channel).toHaveBeenCalledTimes(2)
    expect(fakeSupabase.channel).toHaveBeenNthCalledWith(2, 'chat:conv2', {
      config: { broadcast: { self: false } }
    })

    // The pending clear-timer from the first channel must have been cancelled —
    // advancing past its deadline shouldn't do anything odd to the new state.
    vi.advanceTimersByTime(3000)
    expect(wrapper.vm.remoteTyping).toBe(false)
  })

  it('leave() is idempotent and safe to call before any join()', async () => {
    const wrapper = await mountSuspended(Host)
    expect(() => wrapper.vm.leave()).not.toThrow()
    expect(fakeSupabase.removeChannel).not.toHaveBeenCalled()
    expect(wrapper.vm.remoteTyping).toBe(false)

    // Calling it again should also be a no-op.
    expect(() => wrapper.vm.leave()).not.toThrow()
    expect(fakeSupabase.removeChannel).not.toHaveBeenCalled()
  })

  it('leave() removes the channel, resets remoteTyping, and blocks further pings', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    const joinedChannel = currentChannel
    joinedChannel.subscribeCb?.('SUBSCRIBED')
    joinedChannel.handlers.typing({ payload: { role: 'seller' } })
    expect(wrapper.vm.remoteTyping).toBe(true)

    wrapper.vm.leave()

    expect(fakeSupabase.removeChannel).toHaveBeenCalledWith(joinedChannel)
    expect(wrapper.vm.remoteTyping).toBe(false)

    wrapper.vm.ping()
    expect(joinedChannel.send).not.toHaveBeenCalled()
  })

  it('calls leave() (removeChannel + state reset) when the host component unmounts', async () => {
    const wrapper = await mountSuspended(Host)
    wrapper.vm.join('conv1', { listenFor: 'seller', sendAs: 'customer' })
    const joinedChannel = currentChannel
    joinedChannel.subscribeCb?.('SUBSCRIBED')

    wrapper.unmount()

    expect(fakeSupabase.removeChannel).toHaveBeenCalledWith(joinedChannel)
  })
})
