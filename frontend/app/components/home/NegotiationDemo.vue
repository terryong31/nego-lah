<script setup lang="ts">
/**
 * The negotiation, staged as a scene and scrubbed by a pinned scroll track.
 *
 * The outer element is far taller than the screen while the content inside it
 * sticks to the viewport, so once you reach the section it stops moving and your
 * scrolling drives the conversation instead: one line lands per slice of the
 * track, and scrolling back up takes them away again.
 *
 * The pin runs on phones too, which only works because the whole block has to
 * fit on screen while it is held. On mobile the step rail collapses to a row of
 * three numerals with just the active step's text underneath, and the bubbles
 * lose a little padding — together that is roughly 250px back, enough to hold
 * the scene stationary on a short viewport.
 *
 * No window chrome, no container box, no two-column split — the dialogue is set
 * as editorial type on a 12-column grid, bubbles overlapping and slightly
 * tilted. Prices are pulled out of the copy and underlined with the hero's
 * Memphis wave, which is what carries the RM320 -> RM240 -> RM280 story inline.
 */

type Role = 'agent' | 'buyer'

interface Beat {
  /** Key under `home.dialog` in the locale files. */
  key: string
  role: Role
  /** Desktop placement on the 12-column grid. */
  place: string
  /** Type scale — the contrast between these is what makes it a composition. */
  size: string
  /** Slight rotation, in degrees, so the bubbles feel hand-placed. */
  tilt: number
  /** Vertical overlap into the previous row. */
  pull: string
}

const BEATS: Beat[] = [
  { key: 'm1', role: 'agent', place: 'lg:col-start-1 lg:col-end-8', size: 'text-base sm:text-lg', tilt: -0.8, pull: '' },
  { key: 'm2', role: 'buyer', place: 'lg:col-start-7 lg:col-end-13', size: 'text-base sm:text-lg', tilt: 1.2, pull: 'lg:-mt-2' },
  { key: 'm3', role: 'agent', place: 'lg:col-start-2 lg:col-end-10', size: 'text-lg sm:text-xl', tilt: -0.5, pull: '' },
  { key: 'm4', role: 'buyer', place: 'lg:col-start-8 lg:col-end-13', size: 'text-xl sm:text-2xl lg:text-3xl', tilt: 1.8, pull: 'lg:-mt-3' },
  { key: 'm5', role: 'agent', place: 'lg:col-start-1 lg:col-end-8', size: 'text-base sm:text-lg', tilt: -1.1, pull: 'lg:-mt-5' }
]

/** Each step owns a slice of the script; `upTo` is its last beat (1-indexed). */
const STEPS = [
  { id: 'offer', upTo: 2 },
  { id: 'counter', upTo: 3 },
  { id: 'deal', upTo: 5 }
] as const

/**
 * Where in the track the first line lands and the last one settles. The lead-in
 * lets the section come to rest before anything happens; the tail leaves the
 * finished conversation on screen while you scroll out of the pin.
 */
const LEAD_IN = 0.01
const SETTLED = 0.80

/**
 * Split a line so prices can be set apart. The capturing group keeps the
 * delimiters, and RM320-style figures appear verbatim in all three locales,
 * so this needs no translation of its own.
 */
const PRICE_SPLIT = /(RM\s?\d[\d,]*)/
const isPrice = (chunk: string) => /^RM\s?\d/.test(chunk)
const segments = (text: string) => text.split(PRICE_SPLIT).filter(Boolean)

const track = useTemplateRef<HTMLElement>('track')
const progress = ref(0)
const reducedMotion = ref(false)

/** How many lines have landed, from the reader's position in the track. */
const revealed = computed(() => {
  const p = (progress.value - LEAD_IN) / (SETTLED - LEAD_IN)
  return Math.max(0, Math.min(BEATS.length, Math.ceil(p * BEATS.length)))
})

const activeStep = computed(() => {
  const index = STEPS.findIndex(s => revealed.value <= s.upTo)
  return index === -1 ? STEPS.length - 1 : index
})

/** Clicking a step jumps to the slice of the track that ends on its last line. */
function goToStep(index: number) {
  const el = track.value
  if (!el) return

  const span = el.offsetHeight - window.innerHeight
  if (span <= 0) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }

  const share = STEPS[index]!.upTo / BEATS.length
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

  // Without a pin (mobile, or a viewport taller than the track) there is no
  // travel to measure, so fall back to how far the section has crossed the fold.
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

onMounted(() => {
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  // No motion means no performance: show the finished conversation outright,
  // and drop the tall track so there is no empty scrolling to sit through.
  if (reducedMotion.value) {
    progress.value = 1
    return
  }

  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onScroll, { passive: true })
  measure()
})

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame)
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onScroll)
})
</script>

<template>
  <section
    id="how-it-works"
    class="scroll-mt-24"
  >
    <!-- Headline. The wave underline is the hero's, so the page reads as one hand. -->
    <div class="max-w-3xl">
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
      <p class="mt-6 text-base sm:text-lg text-muted leading-relaxed text-pretty max-w-4xl">
        {{ $t('home.demo.desc') }}
      </p>
    </div>

    <!-- Scroll track: tall on desktop so the scene below can pin inside it -->
    <div
      ref="track"
      class="relative mt-10 sm:mt-14"
      :class="reducedMotion ? '' : 'h-[300vh]'"
    >
      <!--
        Pinned to its own height, not the viewport's. Filling the screen and
        centring left ~290px of slack split above and below the content, which
        read as a dead band under the header and squeezed the conversation.
      -->
      <div
        class="sticky top-[calc(var(--ui-header-height)+1rem)] lg:top-[calc(var(--ui-header-height)+1.5rem)]"
        :class="reducedMotion ? 'static!' : ''"
      >
        <!-- Caption strip: the three steps, tracking progress through the track -->
        <ol class="grid grid-cols-3 gap-x-4 sm:gap-8 pt-6 sm:pt-8 border-t border-default">
          <li
            v-for="(step, index) in STEPS"
            :key="step.id"
          >
            <button
              type="button"
              class="group w-full text-left cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"
              :aria-current="activeStep === index ? 'step' : undefined"
              @click="goToStep(index)"
            >
              <!--
                The stroke WIDTH is constant and only the colours change.
                Toggling -webkit-text-stroke-width from 0 to 1.5px leaves Chrome
                painting no stroke at all on a numeral that had already rendered
                filled, so the step you scrolled past silently vanished.
              -->
              <span
                class="block text-3xl sm:text-5xl font-black font-mono leading-none mb-0 sm:mb-3 transition-colors duration-300 [-webkit-text-stroke-width:1.5px]"
                :class="activeStep === index
                  ? 'text-primary [-webkit-text-stroke-color:var(--ui-primary)]'
                  : 'text-transparent [-webkit-text-stroke-color:var(--ui-border-accented)] group-hover:[-webkit-text-stroke-color:var(--ui-text-muted)]'"
              >
                0{{ index + 1 }}
              </span>
              <span
                class="hidden sm:block font-bold mb-1.5 transition-colors"
                :class="activeStep === index ? 'text-primary' : 'text-highlighted'"
              >
                {{ $t(`home.demo.steps.${step.id}.title`) }}
              </span>
              <span class="hidden sm:block text-sm text-muted leading-relaxed">
                {{ $t(`home.demo.steps.${step.id}.desc`) }}
              </span>
            </button>
          </li>
        </ol>

        <!-- Mobile: only the step you are in carries its text, so three stacked
             blocks don't eat the height the pinned scene needs -->
        <div class="sm:hidden mt-4 min-h-[5.5rem]">
          <p class="font-bold text-primary mb-1">
            {{ $t(`home.demo.steps.${STEPS[activeStep]!.id}.title`) }}
          </p>
          <p class="text-sm text-muted leading-relaxed">
            {{ $t(`home.demo.steps.${STEPS[activeStep]!.id}.desc`) }}
          </p>
        </div>

        <!-- The scene -->
        <div class="relative mt-6 sm:mt-12">
          <!-- Memphis ambience: two shapes, parked in the composition's voids -->
          <div
            aria-hidden="true"
            class="hidden sm:block absolute inset-0 -z-10 overflow-hidden pointer-events-none select-none"
          >
            <svg
              class="absolute top-0 right-[6%] w-20 h-20 text-amber-400/30 animate-memphis-spin-slow"
              viewBox="0 0 54 54"
              fill="none"
            >
              <path
                d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z"
                fill="currentColor"
              />
            </svg>
            <svg
              class="absolute bottom-0 left-[34%] w-28 h-28 text-primary/20 animate-memphis-float"
              viewBox="0 0 100 100"
              fill="none"
            >
              <path
                d="M 10 85 A 40 40 0 0 1 90 85"
                stroke="currentColor"
                stroke-width="11"
                stroke-linecap="round"
              />
            </svg>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-12 gap-y-3 sm:gap-y-6 lg:gap-y-7 lg:gap-x-4">
            <div
              v-for="(beat, index) in BEATS"
              :key="beat.key"
              class="flex items-end gap-2 sm:gap-3 transition-all duration-500 ease-out"
              :class="[
                beat.place,
                beat.pull,
                beat.role === 'buyer' ? 'flex-row-reverse' : '',
                revealed > index ? 'opacity-100' : 'opacity-0 translate-y-6'
              ]"
            >
              <!-- Speaker mark -->
              <span class="shrink-0 pb-1">
                <HomeAgentAvatar
                  v-if="beat.role === 'agent'"
                  class="size-8 sm:size-10"
                />
                <span
                  v-else
                  class="block size-8 sm:size-10 rounded-full border-2 border-dashed border-accented flex items-center justify-center text-[10px] font-bold text-muted"
                >
                  {{ $t('home.demo.you') }}
                </span>
              </span>

              <p
                class="relative min-w-0 px-4 py-2.5 sm:px-6 sm:py-4 font-medium leading-snug text-pretty shadow-sm transition-transform duration-500 ease-out"
                :style="{ transform: revealed > index ? `rotate(${beat.tilt}deg)` : undefined }"
                :class="[
                  beat.size,
                  beat.role === 'agent'
                    ? 'bg-elevated border border-default text-default rounded-[1.75rem] rounded-bl-lg'
                    : 'bg-primary text-inverted rounded-[1.75rem] rounded-br-lg font-bold shadow-primary/20'
                ]"
              >
                <template
                  v-for="(chunk, i) in segments($t(`home.dialog.${beat.key}`))"
                  :key="i"
                >
                  <span
                    v-if="isPrice(chunk)"
                    class="relative inline-block font-extrabold tabular-nums whitespace-nowrap"
                    :class="beat.role === 'agent' ? 'text-primary' : ''"
                  >{{ chunk }}<svg
                    class="absolute -bottom-0.5 left-0 w-full h-1.5 overflow-visible"
                    :class="beat.role === 'agent' ? 'text-primary/40' : 'text-inverted/50'"
                    viewBox="0 0 100 12"
                    fill="none"
                    preserveAspectRatio="none"
                  ><path
                    d="M 0 6 Q 25 12 50 6 T 100 6"
                    stroke="currentColor"
                    stroke-width="5"
                    stroke-linecap="round"
                  /></svg></span>
                  <template v-else>
                    {{ chunk }}
                  </template>
                </template>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
