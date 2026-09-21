import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import AgentPipeline from '~/components/home/AgentPipeline.vue'

/**
 * SPEC-069. The "How it works" walkthrough.
 *
 * Two behaviours matter enough to pin down: a step's video must not touch the
 * network before that step is reached, and a recording that is not in the
 * bucket yet must fail to something deliberate rather than a black rectangle.
 *
 * happy-dom has no layout, so `getBoundingClientRect` returns zeroes and the
 * scroll-driven path cannot be exercised here — the rail's click handler is
 * the seam these tests drive instead, which is also the only path a phone or
 * a reduced-motion visitor ever takes.
 */

enableAutoUnmount(afterEach)

beforeEach(() => {
  // happy-dom has an IntersectionObserver but no layout to trigger it, so it
  // would never fire. Stand in for scrolling the section into view.
  vi.stubGlobal('IntersectionObserver', class {
    constructor(private cb: (entries: { isIntersecting: boolean }[]) => void) {}
    observe() {
      this.cb([{ isIntersecting: true }])
    }

    disconnect() {}
    unobserve() {}
  })
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  }))
  // Autoplay is refused in a headless DOM; the component swallows it.
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn(() => Promise.reject(new Error('not allowed')))
  })
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn()
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('components/home/AgentPipeline.vue', () => {
  it('hands the three steps to UStepper', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    const stepper = wrapper.findComponent({ name: 'UStepper' })
    expect(stepper.exists()).toBe(true)

    // One word per step: a horizontal stepper gives each item ~150px, and
    // the recording is what explains the step. Three is the whole story —
    // upload it, haggle over it, it arrives (SPEC-075).
    const items = stepper.props('items') as { title: string }[]
    expect(items).toHaveLength(3)
    expect(items.map(i => i.title)).toEqual(['Upload', 'Nego', 'Delivery'])

    // A walkthrough, not a wizard: every step is reachable from every other.
    expect(stepper.props('linear')).toBe(false)
  })

  it('carries no caption or subtitle repeating what the video shows', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    expect(wrapper.text()).toContain('How it works')
    expect(wrapper.text()).not.toContain('Take a few photos')
    expect(wrapper.text()).not.toContain('Snap and upload')
    expect(wrapper.text()).not.toContain('Six steps, photo to doorstep')
  })

  it('puts the steps above the recording', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    // Where you are, then what happens there.
    const html = wrapper.html()
    expect(html.indexOf('data-slot="root"')).toBeLessThan(html.indexOf('<video'))
  })

  it('moves to a step when the stepper selects one', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    wrapper.findComponent({ name: 'UStepper' }).vm.$emit('update:modelValue', 2)
    await flushPromises()

    // The video follows the step you picked.
    const shown = wrapper.findAll('video').filter(v => v.classes().includes('opacity-100'))
    expect(shown).toHaveLength(1)
    expect(shown[0]!.attributes('poster')).toContain('delivery.jpg')
  })

  it('warms the current step and the next one, never all three', async () => {
    // SPEC-099. The fetch used to start when a step became ACTIVE, which is the
    // same instant `play()` was called — so the visitor watched the request
    // happen. Step 0 is now warmed a viewport early and step 1 alongside it, so
    // stepping forward does not stall the way the first frame did. Step 2 stays
    // untouched: warming everything up front is the SPEC-045 egress bug again.
    const wrapper = await mountSuspended(AgentPipeline)

    const srcs = wrapper.findAll('video source').map(s => s.attributes('src'))
    expect(srcs).toHaveLength(2)
    expect(srcs.some(s => s?.includes('listing.mp4'))).toBe(true)
    expect(srcs.some(s => s?.includes('haggle.mp4'))).toBe(true)
    expect(srcs.some(s => s?.includes('delivery.mp4'))).toBe(false)
  })

  it('tells the browser to actually buffer a warmed step', async () => {
    // A <source> with preload="none" is the stall with extra steps: the browser
    // is entitled to fetch nothing until play() is called.
    const wrapper = await mountSuspended(AgentPipeline)

    const videos = wrapper.findAll('video')
    expect(videos[0]!.attributes('preload')).toBe('auto')
    expect(videos[1]!.attributes('preload')).toBe('auto')
  })

  it('leaves an unwarmed step inert — no source, no preload', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    const third = wrapper.findAll('video')[2]!
    expect(third.attributes('preload')).toBe('none')
    expect(third.find('source').exists()).toBe(false)
  })

  it('warms the last step only once the one before it is reached', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    wrapper.findComponent({ name: 'UStepper' }).vm.$emit('update:modelValue', 1)
    await flushPromises()

    const srcs = wrapper.findAll('video source').map(s => s.attributes('src'))
    expect(srcs.some(s => s?.includes('delivery.mp4'))).toBe(true)
  })

  it('keeps a video attached once its step has been visited', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    const stepper = wrapper.findComponent({ name: 'UStepper' })
    stepper.vm.$emit('update:modelValue', 1)
    await flushPromises()
    stepper.vm.$emit('update:modelValue', 0)
    await flushPromises()

    // Scrolling back must not throw away what the browser already has.
    const srcs = wrapper.findAll('video source').map(s => s.attributes('src'))
    expect(srcs.some(s => s?.includes('listing.mp4'))).toBe(true)
    expect(srcs.some(s => s?.includes('haggle.mp4'))).toBe(true)
  })

  it('says so while a step has no playable recording', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    // Nothing has decoded yet, which is also what a 404 looks like: a
    // <source> that fails fires `error` on itself, not on the <video>.
    const empty = wrapper.findComponent({ name: 'UEmpty' })
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('Recording coming soon')
  })

  it('drops the placeholder once real frames exist', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    await wrapper.find('video').trigger('loadeddata')
    await flushPromises()

    expect(wrapper.findComponent({ name: 'UEmpty' }).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Recording coming soon')
  })

  it('gives every step a poster so the frame is never empty', async () => {
    const wrapper = await mountSuspended(AgentPipeline)

    const posters = wrapper.findAll('video').map(v => v.attributes('poster'))
    expect(posters).toHaveLength(3)
    expect(posters[0]).toContain('/videos/how-it-works/listing.jpg')
  })
})
