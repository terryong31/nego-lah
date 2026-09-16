<script setup lang="ts">
/**
 * How it works — a pinned walkthrough scrubbed by scroll (SPEC-069).
 *
 * The outer element is far taller than the screen while the content inside it
 * sticks to the viewport, so once you reach the section it stops moving and
 * your scrolling advances the step instead. Roughly one viewport of scroll per
 * step: less and the steps flicker past, more and the page feels jammed.
 *
 * These are recordings of a web app, and nobody ships a bare screen capture —
 * software goes in a device. The browser frame is what turns the .mp4 files
 * into product shots, and it makes the not-yet-recorded state look deliberate
 * rather than missing.
 *
 * The steps are `UStepper`, not a hand-rolled rail. Earlier drafts built the
 * indicator by hand three different ways — mono labels, six accent colours,
 * numbered circles, a sliding underline — and every one was a worse version of
 * a component that was already installed.
 *
 * It sits above the recording: the steps say where you are before the video
 * says what happens there. The video gets every pixel the viewport can spare
 * — no frame, no chrome, nothing around it competing for the height.
 *
 * Its items carry one word each, and that is all the prose in the section.
 * The recording is the explanation — writing the same thing underneath it in
 * a caption was saying it twice, and a subtitle under the heading was saying
 * it a third time. A horizontal stepper gives each item about 150px, so a
 * sentence there wraps to three ragged lines and collides with its
 * neighbours; a single word does not.
 *
 * The pin is desktop-only and off under `prefers-reduced-motion`: hijacking a
 * phone's scroll to play video traps someone who was trying to leave. Below
 * `lg` the same markup becomes a tap-through stepper.
 */
/**
 * The whole story in three beats (SPEC-075): put the item up, haggle over it,
 * it arrives. The middle ceremony — knowledge card, checkout, payment — is in
 * the recordings, not in the rail. Ids are also file names: each stage's
 * recording lives at `videos/how-it-works/<id>.mp4`.
 */
const STAGES = [
  { id: 'listing', icon: 'i-lucide-camera' },
  { id: 'haggle', icon: 'i-lucide-messages-square' },
  { id: 'delivery', icon: 'i-lucide-truck' }
] as const

/**
 * Drop the recordings at `videos/how-it-works/<id>.mp4` in the R2 bucket
 * (`mise run media:sync`), with an optional `<id>.jpg` alongside as the poster.
 */
const config = useRuntimeConfig()
const rawPublic = config.public as Record<string, unknown>
const mediaCdnUrl = String(
  (typeof rawPublic?.mediaCdnUrl === 'string' && rawPublic.mediaCdnUrl) || 'https://media.negolah.my'
).replace(/\/$/, '')

const videoUrl = (id: string) => `${mediaCdnUrl}/videos/how-it-works/${id}.mp4`
const posterUrl = (id: string) => `${mediaCdnUrl}/videos/how-it-works/${id}.jpg`

/** Lead-in lets the section settle before step one; the tail holds the last. */
const LEAD_IN = 0.04
const SETTLED = 0.92

const track = useTemplateRef<HTMLElement>('track')
const progress = ref(0)
const reducedMotion = ref(false)
const isWide = ref(false)

/** The pin only runs where it cannot trap someone. */
const pinned = computed(() => isWide.value && !reducedMotion.value)

const manualStep = ref(0)

/** Position along the walkthrough, 0 to 1, continuous. */
const travelled = computed(() => {
  if (!pinned.value) return (manualStep.value + 0.5) / STAGES.length
  const p = (progress.value - LEAD_IN) / (SETTLED - LEAD_IN)
  return Math.max(0, Math.min(1, p))
})

const activeStep = computed(() => {
  if (!pinned.value) return manualStep.value
  return Math.max(0, Math.min(STAGES.length - 1, Math.floor(travelled.value * STAGES.length)))
})

const active = computed(() => STAGES[activeStep.value]!)

const { t } = useI18n()

const stepperItems = computed(() => STAGES.map(stage => ({
  icon: stage.icon,
  title: t(`home.pipeline.items.${stage.id}`)
})))

/** The stepper is a control as well as an indicator: clicking scrolls. */
function onStepperSelect(value: string | number | undefined) {
  const index = Number(value)
  if (Number.isInteger(index) && index >= 0 && index < STAGES.length) goToStep(index)
}

/**
 * Which steps have been reached, and so are allowed to touch the network. A
 * step never leaves this set: scrolling back up should not re-download what
 * the browser has already decoded.
 */
const reached = ref(new Set<string>())
/**
 * Steps with decodable video. Everything else — not reached, still loading,
 * 404 because the recording is not in the bucket yet — shows the placeholder.
 * A `<source>` that 404s fires `error` on the `<source>` element rather than
 * on `<video>`, so asking "is it ready" is reliable where "did it fail" is not.
 */
const ready = ref(new Set<string>())
const armed = ref(false)

watch([activeStep, armed], () => {
  if (!armed.value) return
  reached.value = new Set(reached.value).add(active.value.id)
}, { immediate: true })

const videoRefs = ref<Record<string, HTMLVideoElement | null>>({})

function setVideoRef(id: string, el: Element | ComponentPublicInstance | null) {
  videoRefs.value[id] = el as HTMLVideoElement | null
}

function onVideoReady(id: string) {
  ready.value = new Set(ready.value).add(id)
}

/** Play the step you are on; pause the rest so three videos never run at once. */
function syncPlayback() {
  for (const stage of STAGES) {
    const el = videoRefs.value[stage.id]
    if (!el) continue
    if (stage.id === active.value.id && armed.value) {
      el.muted = true
      el.play().catch(() => {
        // Autoplay refused: the poster stays, which is a fine still frame.
      })
    } else if (!el.paused) {
      el.pause()
    }
  }
}

watch([activeStep, armed], () => nextTick(syncPlayback))

/** Clicking a step jumps to the slice of the track that shows it. */
function goToStep(index: number) {
  // A click is proof the section is on screen, and is worth trusting over the
  // observer: if `IntersectionObserver` is missing or never fires, this is the
  // only thing that would ever let a video load.
  armed.value = true
  manualStep.value = index

  const el = track.value
  if (!el || !pinned.value) return

  const span = el.offsetHeight - window.innerHeight
  if (span <= 0) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }

  // Land mid-slice rather than on its edge, where a pixel of drift would show
  // the neighbouring step instead.
  const share = (index + 0.5) / STAGES.length
  const target = LEAD_IN + (SETTLED - LEAD_IN) * share
  const top = el.getBoundingClientRect().top + window.scrollY + span * target
  window.scrollTo({ top, behavior: 'smooth' })
}

let frame = 0

function measure() {
  const el = track.value
  if (!el) return

  const rect = el.getBoundingClientRect()
  const span = rect.height - window.innerHeight

  // Without a pin there is no travel to measure.
  if (span <= 0) {
    progress.value = Math.max(0, Math.min(1, 1 - rect.bottom / (rect.height + window.innerHeight)))
    return
  }

  progress.value = Math.max(0, Math.min(1, -rect.top / span))
}

function onScroll() {
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    measure()
  })
}

let observer: IntersectionObserver | null = null
let wideQuery: MediaQueryList | null = null

function onWideChange(event: MediaQueryListEvent | MediaQueryList) {
  isWide.value = event.matches
}

onMounted(() => {
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  wideQuery = window.matchMedia('(min-width: 1024px)')
  onWideChange(wideQuery)
  wideQuery.addEventListener('change', onWideChange)

  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onScroll, { passive: true })
  measure()

  // Nothing is fetched until the section is nearly on screen.
  if ('IntersectionObserver' in window && track.value) {
    observer = new IntersectionObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      if (entry.isIntersecting) {
        armed.value = true
      } else {
        for (const stage of STAGES) videoRefs.value[stage.id]?.pause()
      }
    }, { rootMargin: '200px' })
    observer.observe(track.value)
  } else {
    armed.value = true
  }
})

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame)
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onScroll)
  wideQuery?.removeEventListener('change', onWideChange)
  observer?.disconnect()
})
</script>

<template>
  <section
    id="how-it-works"
    class="scroll-mt-24"
  >
    <!--
      Memphis accents, in the hero's own vocabulary — the orange arch with its
      pink dot, the yellow sunburst, the purple zigzag, the dashed turquoise
      donut. They hang off a `w-fit` wrapper rather than the full-width
      heading, so they sit against the words instead of drifting out to the
      container edge, and they are the first thing to go on a narrow screen.
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

    <div
      ref="track"
      class="relative mt-8 sm:mt-10"
      :style="pinned ? { height: `${STAGES.length * 100}vh` } : undefined"
    >
      <div
        class="lg:sticky lg:top-(--ui-header-height) lg:h-[calc(100svh_-_var(--ui-header-height))] flex flex-col justify-center gap-5 sm:gap-6 py-4 sm:py-6"
        :class="pinned ? '' : 'lg:static! lg:h-auto!'"
      >
        <!-- The three steps. `linear: false` because this is a walkthrough,
             not a wizard: every step is reachable from every other.

             The two accents flank the rail rather than the recording: the
             video runs nearly the full container width, so anything beside it
             would either overlap it or be clipped. `xl` only, which is where
             the gutter is wide enough to hold them. -->
        <div class="relative w-full max-w-4xl mx-auto">
          <svg
            aria-hidden="true"
            class="hidden xl:block absolute -left-24 top-1/2 -translate-y-1/2 w-13 h-6 pointer-events-none select-none opacity-85 animate-memphis-float-reverse"
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

          <UStepper
            :model-value="activeStep"
            :items="stepperItems"
            color="primary"
            size="md"
            :linear="false"
            :ui="{ wrapper: 'px-2' }"
            @update:model-value="onStepperSelect"
          />

          <svg
            aria-hidden="true"
            class="hidden xl:block absolute -right-24 top-1/2 -translate-y-1/2 w-12 h-12 pointer-events-none select-none opacity-90 animate-memphis-float"
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
        <!-- The recording, as large as the viewport allows. The whole scene
             has to fit one screen or `justify-center` clips it at both ends;
             everything else here is fixed height, so the video takes what is
             left. The underscores matter: a Tailwind arbitrary value cannot
             contain spaces and `calc` needs them around `-`, so writing this
             without the escapes yields invalid CSS that is silently dropped
             and the heading gets clipped. -->
        <div class="w-full mx-auto max-w-5xl lg:max-w-[min(80rem,max(22rem,calc((100svh_-_16rem)*16/9)))]">
          <div class="rounded-xl sm:rounded-2xl overflow-hidden bg-elevated ring-1 ring-default shadow-2xl shadow-black/10 dark:shadow-black/40">
            <!-- No chrome around it: a fake browser bar is decoration that
                 costs 40px of height the recording should have instead. -->
            <div class="relative aspect-video w-full bg-elevated">
              <video
                v-for="stage in STAGES"
                :key="stage.id"
                :ref="el => setVideoRef(stage.id, el)"
                class="absolute inset-0 w-full h-full object-cover pointer-events-none select-none transition-opacity duration-500 ease-out"
                :class="stage.id === active.id ? 'opacity-100' : 'opacity-0'"
                playsinline
                muted
                loop
                preload="none"
                tabindex="-1"
                disablepictureinpicture
                disableremoteplayback
                :poster="posterUrl(stage.id)"
                @loadeddata="onVideoReady(stage.id)"
              >
                <source
                  v-if="reached.has(stage.id)"
                  :src="videoUrl(stage.id)"
                  type="video/mp4"
                >
              </video>

              <!-- No recording for this step yet. The files land after
                   this ships, so this IS the design for now, not a gap
                   waiting for one. Covered the moment real frames exist. -->
              <UEmpty
                v-if="!ready.has(active.id)"
                variant="naked"
                size="lg"
                :icon="active.icon"
                :description="$t('home.pipeline.soon')"
                :ui="{ description: 'font-medium' }"
                class="absolute inset-0"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
