import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import ProductVideoShowcase from '~/components/home/ProductVideoShowcase.vue'

describe('components/home/ProductVideoShowcase.vue', () => {
  beforeEach(() => {
    // Mock HTMLMediaElement methods for happy-dom
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
    window.HTMLMediaElement.prototype.pause = vi.fn()
  })

  it('renders the #how-it-works section with headline and Memphis wave', async () => {
    const wrapper = await mountSuspended(ProductVideoShowcase)

    const section = wrapper.find('#how-it-works')
    expect(section.exists()).toBe(true)

    // Heading h2 exists
    const h2 = wrapper.find('h2')
    expect(h2.exists()).toBe(true)

    // Memphis wave decorative SVG inside heading
    const waveSvg = h2.find('svg')
    expect(waveSvg.exists()).toBe(true)
  })

  it('renders the autonomous HTML5 video element with muted, loop, and playsinline', async () => {
    const wrapper = await mountSuspended(ProductVideoShowcase, {
      props: {
        src: '/videos/negotiation-demo.mp4',
        poster: '/images/hero-illustration.jpg'
      }
    })

    const video = wrapper.find('video')
    expect(video.exists()).toBe(true)
    expect(video.attributes('playsinline')).toBeDefined()
    expect(video.attributes('autoplay')).toBeDefined()
    expect(video.attributes('loop')).toBeDefined()
    expect(video.attributes('poster')).toBe('/images/hero-illustration.jpg')
    expect(video.classes()).toContain('pointer-events-none')

    const source = video.find('source')
    expect(source.exists()).toBe(true)
    expect(source.attributes('src')).toBe('/videos/negotiation-demo.mp4')
  })

  it('resolves default video source to Supabase CDN or fallback when src prop is omitted', async () => {
    const wrapper = await mountSuspended(ProductVideoShowcase)

    const video = wrapper.find('video')
    expect(video.exists()).toBe(true)

    const source = video.find('source')
    expect(source.exists()).toBe(true)
    const src = source.attributes('src')
    expect(src).toMatch(/(videos\/negotiation-demo\.mp4)/)
  })

  it('renders Corporate Memphis floating decorative SVGs around the video frame', async () => {
    const wrapper = await mountSuspended(ProductVideoShowcase)

    // Memphis floating SVGs
    expect(wrapper.find('.animate-memphis-float').exists()).toBe(true)
    expect(wrapper.find('.animate-memphis-spin-slow').exists()).toBe(true)
    expect(wrapper.find('.animate-memphis-pulse-subtle').exists()).toBe(true)

    // Starburst fill
    const html = wrapper.html()
    expect(html).toContain('#FBBF24') // Yellow starburst
    expect(html).toContain('#FB923C') // Orange arch
    expect(html).toContain('#06B6D4') // Cyan donut
  })

  it('does NOT render manual video controls or window chrome', async () => {
    const wrapper = await mountSuspended(ProductVideoShowcase)

    // No window titlebar / traffic lights
    expect(wrapper.find('[data-testid="window-titlebar"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="window-dot"]').exists()).toBe(false)

    // No manual play/pause button overlay or scrubber
    expect(wrapper.find('[data-testid="play-pause-btn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="video-scrubber"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="mute-btn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fullscreen-btn"]').exists()).toBe(false)
  })

  it('does NOT render the removed 3-card block', async () => {
    const wrapper = await mountSuspended(ProductVideoShowcase)

    expect(wrapper.text()).not.toContain('01')
    expect(wrapper.text()).not.toContain('Name your price')
    expect(wrapper.text()).not.toContain('The agent counters')
    expect(wrapper.text()).not.toContain('Shake on it')
  })
})
