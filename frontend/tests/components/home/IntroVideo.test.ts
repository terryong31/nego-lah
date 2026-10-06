import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import IntroVideo from '~/components/home/IntroVideo.vue'

/**
 * SPEC-100. One motion-graphics intro in place of the three-step walkthrough.
 *
 * What matters: the file must not touch the network before the visitor is
 * near it (SPEC-045), must be buffering by the time they arrive (SPEC-099),
 * and must start muted because a browser refuses anything else.
 *
 * happy-dom has no layout, so the observers never fire on their own. Each one
 * is captured by its `rootMargin` and fired by hand, which is how the two
 * questions — "start fetching" and "start playing" — are told apart.
 */

enableAutoUnmount(afterEach)

type Entry = { isIntersecting: boolean }
let observers: Map<string, (entries: Entry[]) => void>
let reducedMotion: boolean
let play: ReturnType<typeof vi.fn>
let pause: ReturnType<typeof vi.fn>

/** The fetch observer: a full viewport of runway. */
const approach = () => observers.get('100% 0px')?.([{ isIntersecting: true }])
/** The play observer: on screen, give or take 200px. */
const onScreen = (isIntersecting: boolean) => observers.get('200px')?.([{ isIntersecting }])

beforeEach(() => {
  observers = new Map()
  reducedMotion = false
  vi.stubGlobal('IntersectionObserver', class {
    constructor(cb: (entries: Entry[]) => void, options?: { rootMargin?: string }) {
      observers.set(options?.rootMargin ?? '', cb)
    }

    observe() {}
    disconnect() {}
    unobserve() {}
  })
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('reduce') ? reducedMotion : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  }))
  play = vi.fn(() => Promise.resolve())
  pause = vi.fn()
  Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: play })
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: pause })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('components/home/IntroVideo.vue', () => {
  it('is one video, not a stepper over three', async () => {
    const wrapper = await mountSuspended(IntroVideo)

    expect(wrapper.findAll('video')).toHaveLength(1)
    expect(wrapper.findComponent({ name: 'UStepper' }).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('coming soon')
  })

  it('touches nothing before the visitor approaches', async () => {
    const wrapper = await mountSuspended(IntroVideo)

    expect(wrapper.find('video source').exists()).toBe(false)
    expect(wrapper.find('video').attributes('preload')).toBe('none')
  })

  it('starts buffering a viewport ahead of the section', async () => {
    const wrapper = await mountSuspended(IntroVideo)

    approach()
    await flushPromises()

    expect(wrapper.find('video source').attributes('src')).toMatch(/\/videos\/intro\.mp4$/)
    expect(wrapper.find('video').attributes('preload')).toBe('auto')
    // Fetching is not playing: that waits for the section itself.
    expect(play).not.toHaveBeenCalled()
  })

  it('is never a blank frame, and starts muted inline', async () => {
    const wrapper = await mountSuspended(IntroVideo)
    const video = wrapper.find('video')

    expect(video.attributes('poster')).toMatch(/\/videos\/intro\.jpg$/)
    expect(video.attributes()).toHaveProperty('playsinline')
    expect((video.element as HTMLVideoElement).muted).toBe(true)
  })

  it('plays on screen and pauses off it', async () => {
    await mountSuspended(IntroVideo)

    onScreen(true)
    await flushPromises()
    expect(play).toHaveBeenCalled()

    onScreen(false)
    await flushPromises()
    expect(pause).toHaveBeenCalled()
  })

  it('arriving without the approach still fetches', async () => {
    const wrapper = await mountSuspended(IntroVideo)

    onScreen(true)
    await flushPromises()

    expect(wrapper.find('video source').exists()).toBe(true)
  })

  it('toggles sound from a labelled button', async () => {
    const wrapper = await mountSuspended(IntroVideo)
    const video = wrapper.find('video').element as HTMLVideoElement
    const sound = () => wrapper.find('[data-testid="intro-sound"]')

    expect(sound().attributes('aria-label')).toBe('Turn sound on')

    await sound().trigger('click')
    await flushPromises()
    expect(video.muted).toBe(false)
    expect(sound().attributes('aria-label')).toBe('Turn sound off')

    await sound().trigger('click')
    await flushPromises()
    expect(video.muted).toBe(true)
  })

  it('waits to be asked under reduced motion', async () => {
    reducedMotion = true
    const wrapper = await mountSuspended(IntroVideo)

    onScreen(true)
    await flushPromises()
    expect(play).not.toHaveBeenCalled()

    await wrapper.find('[data-testid="intro-play"]').trigger('click')
    await flushPromises()
    expect(play).toHaveBeenCalled()
    expect(wrapper.find('video source').exists()).toBe(true)
  })
})
