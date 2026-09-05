<script setup lang="ts">
/**
 * Product Walkthrough Video Showcase (SPEC-026)
 *
 * Cinematic, autonomous product walkthrough video showcase.
 * Plays automatically when scrolled into view and pauses when out of view.
 * Unobtrusive, non-interactive showcase framed with Corporate Memphis design accents
 * and ambient lighting.
 */

interface Props {
  /** Path to MP4/WebM video asset */
  src?: string
  /** Fallback poster image */
  poster?: string
  /** Whether to automatically play/pause based on viewport visibility */
  autoPlayOnScroll?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  src: undefined,
  poster: '/images/hero-illustration.jpg',
  autoPlayOnScroll: true
})

const config = useRuntimeConfig()
const rawPublic = config.public as Record<string, unknown>
const supabaseSub = rawPublic?.supabase as Record<string, unknown> | undefined
const supabaseUrl = (typeof rawPublic?.supabaseUrl === 'string' && rawPublic.supabaseUrl)
  || (typeof supabaseSub?.url === 'string' && supabaseSub.url)
  || (typeof process !== 'undefined' ? (process.env?.NUXT_PUBLIC_SUPABASE_URL || process.env?.SUPABASE_URL) : undefined)

const videoSource = computed(() => {
  if (props.src) return props.src
  if (supabaseUrl) {
    return `${supabaseUrl.replace(/\/$/, '')}/storage/v1/object/public/images/videos/negotiation-demo.mp4`
  }
  return '/videos/negotiation-demo.mp4'
})

const videoRef = useTemplateRef<HTMLVideoElement>('videoRef')
const containerRef = useTemplateRef<HTMLElement>('containerRef')

let observer: IntersectionObserver | null = null

onMounted(() => {
  const el = videoRef.value
  if (el) {
    el.muted = true
  }

  // Viewport intersection observer for autonomous play / pause
  if (props.autoPlayOnScroll && typeof window !== 'undefined' && 'IntersectionObserver' in window && containerRef.value) {
    observer = new IntersectionObserver((entries) => {
      const entry = entries[0]
      if (!entry || !videoRef.value) return

      if (entry.isIntersecting && entry.intersectionRatio >= 0.25) {
        videoRef.value.muted = true
        videoRef.value.play().catch(() => {
          // Handled gracefully if browser blocks background autoplay
        })
      } else if (!entry.isIntersecting && !videoRef.value.paused) {
        videoRef.value.pause()
      }
    }, { threshold: [0.1, 0.3] })

    observer.observe(containerRef.value)
  }

  onBeforeUnmount(() => {
    if (observer) observer.disconnect()
  })
})
</script>

<template>
  <section
    id="how-it-works"
    class="scroll-mt-24 relative"
  >
    <!-- Section Header with Memphis Wave -->
    <div class="max-w-xl mb-8 sm:mb-12 text-center mx-auto">
      <!-- Main Headline with Wave -->
      <h2 class="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-highlighted leading-[1.08]">
        {{ $t('home.demo.titleLead') }}
        <span class="relative inline-block text-primary">
          {{ $t('home.demo.titleAccent') }}
          <svg
            class="absolute -bottom-1 sm:-bottom-2 left-0 w-full h-3 text-primary/40 overflow-visible"
            viewBox="0 0 100 12"
            fill="none"
            preserveAspectRatio="none"
          >
            <path
              d="M 0 6 Q 25 12 50 6 T 100 6"
              stroke="currentColor"
              stroke-width="4.5"
              stroke-linecap="round"
            />
          </svg>
        </span>
        {{ $t('home.demo.titleTail') }}
      </h2>
      <p class="mt-4 text-base sm:text-lg text-muted leading-relaxed text-pretty max-w-5xl">
        {{ $t('home.demo.desc') }}
      </p>
    </div>

    <!-- Video Showcase Wrapper with Floating Memphis Accents -->
    <div
      ref="containerRef"
      class="relative w-full mx-auto"
    >
      <!-- Background Ambient Glow behind video -->
      <div
        class="absolute -inset-2 sm:-inset-4 bg-gradient-to-tr from-primary/20 via-emerald-500/10 to-purple-500/20 rounded-3xl blur-2xl opacity-60 dark:opacity-35 -z-10 pointer-events-none"
        aria-hidden="true"
      />

      <!-- ================= MEMPHIS FLOATING SVGS (Matching UHero) ================= -->

      <!-- 1. Top-Left: Orange Arch & Pink Dot (floating above the top-left edge) -->
      <div
        class="absolute -top-6 sm:-top-8 -left-3 sm:-left-6 z-10 pointer-events-none animate-memphis-float"
        aria-hidden="true"
      >
        <svg
          width="60"
          height="60"
          viewBox="0 0 70 70"
          fill="none"
          class="w-10 h-10 sm:w-14 sm:h-14 drop-shadow-md"
        >
          <path
            d="M 10 60 A 25 25 0 0 1 60 60"
            stroke="#FB923C"
            stroke-width="8"
            stroke-linecap="round"
          />
          <circle
            cx="35"
            cy="20"
            r="6"
            fill="#F43F5E"
          />
        </svg>
      </div>

      <!-- 2. Top-Right: Rotating 8-Point Yellow Sunburst Star -->
      <div
        class="absolute -top-5 sm:-top-7 -right-2 sm:-right-4 z-10 pointer-events-none animate-memphis-spin-slow"
        aria-hidden="true"
      >
        <svg
          width="48"
          height="48"
          viewBox="0 0 54 54"
          fill="none"
          class="w-9 h-9 sm:w-12 sm:h-12 drop-shadow-md"
        >
          <path
            d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z"
            fill="#FBBF24"
            opacity="0.9"
          />
        </svg>
      </div>

      <!-- 3. Left Mid-Height: Purple Zigzag Ribbon -->
      <div
        class="hidden sm:block absolute top-1/2 -translate-y-1/2 -left-6 lg:-left-8 z-10 pointer-events-none opacity-85 animate-memphis-float-reverse"
        aria-hidden="true"
      >
        <svg
          width="56"
          height="28"
          viewBox="0 0 80 40"
          fill="none"
          class="w-11 h-6 lg:w-13 lg:h-7 drop-shadow-sm"
        >
          <path
            d="M 5 20 L 20 5 L 35 35 L 50 5 L 65 35 L 75 20"
            stroke="#A855F7"
            stroke-width="6"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <!-- 4. Bottom-Left: Colorful Dotted Matrix -->
      <div
        class="hidden sm:block absolute -bottom-5 sm:-bottom-7 -left-2 sm:-left-4 z-10 pointer-events-none opacity-75 dark:opacity-50 animate-memphis-pulse-subtle"
        aria-hidden="true"
      >
        <div class="grid grid-cols-4 gap-2 sm:gap-2.5">
          <div class="size-2 sm:size-2.5 rounded-full bg-primary" />
          <div class="size-2 sm:size-2.5 rounded-full bg-amber-400" />
          <div class="size-2 sm:size-2.5 rounded-full bg-rose-400" />
          <div class="size-2 sm:size-2.5 rounded-full bg-purple-400" />
          <div class="size-2 sm:size-2.5 rounded-full bg-sky-400" />
          <div class="size-2 sm:size-2.5 rounded-full bg-primary" />
          <div class="size-2 sm:size-2.5 rounded-full bg-amber-400" />
          <div class="size-2 sm:size-2.5 rounded-full bg-rose-400" />
        </div>
      </div>

      <!-- 5. Bottom-Right: Pastel Turquoise Donut & Confetti Pill -->
      <div
        class="absolute -bottom-5 sm:-bottom-7 -right-2 sm:-right-5 z-10 pointer-events-none opacity-90 animate-memphis-float"
        aria-hidden="true"
      >
        <svg
          width="52"
          height="52"
          viewBox="0 0 60 60"
          fill="none"
          class="w-10 h-10 sm:w-13 sm:h-13 drop-shadow-md"
        >
          <circle
            cx="30"
            cy="30"
            r="18"
            stroke="#06B6D4"
            stroke-width="6.5"
            stroke-dasharray="14 7"
          />
          <rect
            x="42"
            y="6"
            width="7"
            height="16"
            rx="3.5"
            fill="#EC4899"
            transform="rotate(35 42 6)"
          />
        </svg>
      </div>

      <!-- ================= CINEMATIC VIDEO FRAME (Autonomous Playback) ================= -->
      <div
        data-testid="video-showcase-frame"
        class="relative aspect-video w-full rounded-2xl sm:rounded-3xl overflow-hidden border border-default/60 dark:border-white/10 ring-1 ring-black/5 dark:ring-white/10 bg-neutral-950 shadow-2xl shadow-primary/10 transition-all duration-300"
      >
        <video
          ref="videoRef"
          class="w-full h-full object-cover pointer-events-none select-none"
          playsinline
          autoplay
          muted
          loop
          tabindex="-1"
          disablepictureinpicture
          disableremoteplayback
          :poster="poster"
        >
          <source
            :src="videoSource"
            type="video/mp4"
          >
          Your browser does not support HTML5 video playback.
        </video>
      </div>
    </div>
  </section>
</template>
