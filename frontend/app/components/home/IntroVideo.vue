<script setup lang="ts">
/**
 * How it works — one motion-graphics intro (SPEC-100).
 *
 * This used to be a scroll-pinned stepper over three screen recordings that
 * were never recorded, so every visitor saw "coming soon" three times. The
 * video is now one file, made as code in `video/` (ADR-0031) and served from
 * the media bucket like every other video.
 *
 * It starts muted because a browser will not autoplay anything else, and a
 * button hands the sound to anyone who wants it. Under `prefers-reduced-motion`
 * nothing moves until the visitor presses play.
 */
const config = useRuntimeConfig()
const rawPublic = config.public as Record<string, unknown>
const mediaCdnUrl = String(
  (typeof rawPublic?.mediaCdnUrl === 'string' && rawPublic.mediaCdnUrl) || 'https://media.negolah.my'
).replace(/\/$/, '')

/** Rendered by `mise run video:render`, published by `mise run media:sync`. */
const videoUrl = `${mediaCdnUrl}/videos/intro.mp4`
const posterUrl = `${mediaCdnUrl}/videos/intro.jpg`

const { t } = useI18n()

const section = useTemplateRef<HTMLElement>('section')
const video = useTemplateRef<HTMLVideoElement>('video')

/**
 * Whether the file may touch the network. It never goes back to false:
 * scrolling away should not throw away what has been buffered.
 *
 * SPEC-045: nothing is fetched for a visitor who never comes near. SPEC-099:
 * "near" starts a viewport early, so the request is not made at the moment of
 * `play()`. `auto` matters — a `<source>` under `preload="none"` may fetch
 * nothing until it is asked to play, which is the stall again.
 */
const warm = ref(false)
const onScreen = ref(false)
const reducedMotion = ref(false)
const muted = ref(true)
const playing = ref(false)
/** Autoplay refused (low-power mode, a strict browser): offer the button. */
const refused = ref(false)

const showPlay = computed(() => !playing.value && (reducedMotion.value || refused.value))
const soundLabel = computed(() => (muted.value ? t('home.intro.unmute') : t('home.intro.mute')))

async function start() {
  const el = video.value
  if (!el) return
  warm.value = true
  await nextTick()
  try {
    await el.play()
    refused.value = false
  } catch {
    // The poster stays, which is a fine still frame; the button takes over.
    refused.value = true
  }
}

/** A click is proof the section is on screen, and outranks the observer. */
function onPlayClick() {
  void start()
}

function toggleSound() {
  const el = video.value
  if (!el) return
  muted.value = !muted.value
  el.muted = muted.value
  // Unmuting is a user gesture: the one moment a browser lets sound play.
  if (el.paused) void start()
}

let warmObserver: IntersectionObserver | null = null
let playObserver: IntersectionObserver | null = null

onMounted(() => {
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  // `muted` as an attribute is not reflected by Vue; set the property so the
  // first `play()` is one the browser allows.
  if (video.value) video.value.muted = true

  const el = section.value
  if (!el || !('IntersectionObserver' in window)) {
    warm.value = true
    return
  }

  // Fetch: a full viewport of runway, then never again.
  warmObserver = new IntersectionObserver((entries) => {
    if (!entries[0]?.isIntersecting) return
    warm.value = true
    warmObserver?.disconnect()
    warmObserver = null
  }, { rootMargin: '100% 0px' })
  warmObserver.observe(el)

  // Play: on screen, give or take 200px.
  playObserver = new IntersectionObserver((entries) => {
    const entry = entries[0]
    if (!entry) return
    onScreen.value = entry.isIntersecting
    if (entry.isIntersecting) {
      warm.value = true
      if (!reducedMotion.value) void start()
    } else {
      video.value?.pause()
    }
  }, { rootMargin: '200px' })
  playObserver.observe(el)
})

onBeforeUnmount(() => {
  warmObserver?.disconnect()
  playObserver?.disconnect()
})
</script>

<template>
  <section
    id="how-it-works"
    ref="section"
    class="scroll-mt-24"
  >
    <!--
      Memphis accents, in the hero's own vocabulary — the orange arch with its
      pink dot and the yellow sunburst. They hang off a `w-fit` wrapper so they
      sit against the words, and are the first thing to go on a narrow screen.
    -->
    <div class="relative w-fit mx-auto">
      <svg
        aria-hidden="true"
        class="hidden sm:block absolute -left-16 lg:-left-20 top-0 w-11 h-11 lg:w-14 lg:h-14 pointer-events-none select-none animate-memphis-float"
        viewBox="0 0 70 70"
        fill="none"
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

      <h2 class="text-center text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-highlighted leading-[1.1] text-balance">
        {{ $t('home.pipeline.title') }}
      </h2>

      <svg
        aria-hidden="true"
        class="hidden sm:block absolute -right-14 lg:-right-16 -top-3 w-9 h-9 lg:w-11 lg:h-11 pointer-events-none select-none animate-memphis-spin-slow"
        viewBox="0 0 54 54"
        fill="none"
      >
        <path
          d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z"
          fill="#FBBF24"
          opacity="0.9"
        />
      </svg>
    </div>

    <!-- Sized so the whole frame fits one screen under the header and the
         heading. The underscores matter: an arbitrary value cannot contain
         spaces and `calc` needs them around `-`. -->
    <div class="relative mt-8 sm:mt-10 w-full mx-auto max-w-5xl lg:max-w-[min(72rem,max(22rem,calc((100svh_-_14rem)*16/9)))]">
      <!-- The purple zigzag and the dashed turquoise donut clip the frame's
           corners, the way the shapes overlap edges inside the video. -->
      <svg
        aria-hidden="true"
        class="hidden md:block absolute -left-8 -top-6 z-10 w-16 h-8 pointer-events-none select-none animate-memphis-float-reverse"
        viewBox="0 0 80 40"
        fill="none"
      >
        <path
          d="M 5 20 L 20 5 L 35 35 L 50 5 L 65 35 L 75 20"
          stroke="#A855F7"
          stroke-width="5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>

      <div class="relative aspect-video w-full rounded-xl sm:rounded-2xl overflow-hidden bg-elevated ring-1 ring-default shadow-2xl shadow-black/10 dark:shadow-black/40">
        <video
          ref="video"
          class="absolute inset-0 w-full h-full object-cover"
          playsinline
          muted
          loop
          :preload="warm ? 'auto' : 'none'"
          disablepictureinpicture
          disableremoteplayback
          :poster="posterUrl"
          @play="playing = true"
          @pause="playing = false"
        >
          <source
            v-if="warm"
            :src="videoUrl"
            type="video/mp4"
          >
        </video>

        <UButton
          v-if="showPlay"
          data-testid="intro-play"
          icon="i-lucide-play"
          size="xl"
          color="neutral"
          variant="solid"
          :aria-label="$t('home.intro.play')"
          class="absolute inset-0 m-auto size-16 justify-center rounded-full shadow-lg"
          @click="onPlayClick"
        />

        <UButton
          data-testid="intro-sound"
          :icon="muted ? 'i-lucide-volume-x' : 'i-lucide-volume-2'"
          size="md"
          color="neutral"
          variant="solid"
          :aria-label="soundLabel"
          :aria-pressed="!muted"
          class="absolute right-3 bottom-3 sm:right-4 sm:bottom-4 rounded-full shadow-md"
          @click="toggleSound"
        />
      </div>

      <svg
        aria-hidden="true"
        class="hidden md:block absolute -right-7 -bottom-7 z-10 w-14 h-14 pointer-events-none select-none animate-memphis-float"
        viewBox="0 0 60 60"
        fill="none"
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
  </section>
</template>
