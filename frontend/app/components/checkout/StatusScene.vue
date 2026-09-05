<script setup lang="ts">
/**
 * The illustrated mark at the top of a checkout outcome.
 *
 * Same Corporate Memphis vocabulary as the landing hero — a flat stroked glyph
 * ringed by floating accent shapes — so the end of the funnel looks like the
 * start of it. The accents thin out as the news gets worse: a confirmed
 * purchase earns confetti, a refund gets two shapes, an error gets one, and
 * the pending state spins a dashed ring instead of a progress bar.
 */
type Variant = 'success' | 'refunded' | 'error' | 'pending'

const props = withDefaults(defineProps<{ variant?: Variant }>(), {
  variant: 'success'
})

const RING_COLOR: Record<Variant, string> = {
  success: 'text-primary',
  refunded: 'text-warning',
  error: 'text-error',
  pending: 'text-primary'
}

const ACCENTS: Record<Variant, readonly string[]> = {
  success: ['arch', 'star', 'zigzag', 'donut'],
  refunded: ['arch', 'donut'],
  error: ['zigzag'],
  pending: ['arch', 'donut']
}

const ringColor = computed(() => RING_COLOR[props.variant])
const accents = computed(() => ACCENTS[props.variant])
const has = (name: string) => accents.value.includes(name)
</script>

<template>
  <div
    class="relative mx-auto size-32 sm:size-36 select-none"
    aria-hidden="true"
  >
    <!-- Centre mark -->
    <svg
      viewBox="0 0 100 100"
      fill="none"
      class="relative z-10 size-full"
      :class="ringColor"
    >
      <circle
        cx="50"
        cy="50"
        r="34"
        fill="currentColor"
        class="opacity-10"
      />
      <circle
        v-if="variant !== 'pending'"
        cx="50"
        cy="50"
        r="34"
        stroke="currentColor"
        stroke-width="5"
      />

      <!-- Confirmed -->
      <path
        v-if="variant === 'success'"
        d="M34 51 L45 62 L67 39"
        stroke="currentColor"
        stroke-width="8"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="animate-memphis-pop"
      />

      <!-- Refunded: a return arc -->
      <template v-else-if="variant === 'refunded'">
        <path
          d="M66 60 A 18 18 0 1 0 50 32"
          stroke="currentColor"
          stroke-width="7"
          stroke-linecap="round"
        />
        <path
          d="M50 23 L50 41 L39 32 Z"
          fill="currentColor"
        />
      </template>

      <!-- Error -->
      <template v-else-if="variant === 'error'">
        <path
          d="M39 39 L61 61"
          stroke="currentColor"
          stroke-width="8"
          stroke-linecap="round"
        />
        <path
          d="M61 39 L39 61"
          stroke="currentColor"
          stroke-width="8"
          stroke-linecap="round"
        />
      </template>
    </svg>

    <!-- Pending: the ring itself is the spinner, so no separate progress bar -->
    <svg
      v-if="variant === 'pending'"
      viewBox="0 0 100 100"
      fill="none"
      class="absolute inset-0 z-10 size-full animate-memphis-spin-slow"
      :class="ringColor"
    >
      <circle
        cx="50"
        cy="50"
        r="34"
        stroke="currentColor"
        stroke-width="5"
        stroke-linecap="round"
        stroke-dasharray="26 16"
      />
    </svg>

    <!-- Accents, in the hero's palette -->
    <div
      v-if="has('arch')"
      class="absolute -top-1 -left-4 animate-memphis-float"
    >
      <svg
        viewBox="0 0 70 70"
        fill="none"
        class="size-11"
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

    <div
      v-if="has('star')"
      class="absolute -top-2 -right-3 animate-memphis-spin-slow"
    >
      <svg
        viewBox="0 0 54 54"
        fill="none"
        class="size-9"
      >
        <path
          d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z"
          fill="#FBBF24"
          class="opacity-90"
        />
      </svg>
    </div>

    <div
      v-if="has('zigzag')"
      class="absolute -bottom-1 -left-5 animate-memphis-float-reverse"
    >
      <svg
        viewBox="0 0 80 40"
        fill="none"
        class="w-12 h-6"
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

    <div
      v-if="has('donut')"
      class="absolute -bottom-2 -right-4 animate-memphis-float"
    >
      <svg
        viewBox="0 0 60 60"
        fill="none"
        class="size-11"
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
        />
      </svg>
    </div>
  </div>
</template>
