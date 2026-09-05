<script setup lang="ts">
/**
 * The checkout hand-off at the end of a negotiation.
 *
 * The agent emits the link as plain markdown ("[Pay RM1000 Now](https://…)"),
 * so the label is the only place the agreed amount exists. We parse it out and
 * make the *price* the hero — that number is the whole point of the haggle —
 * with Stripe demoted to a trust footnote rather than a branded tile.
 *
 * Drawn in the site's Corporate Memphis vocabulary: flat stroked shapes in the
 * hero's palette, a dashed rule that reads as a receipt perforation, and the
 * same float used by the hero accents. Shared by the customer chat and the
 * admin console so both ends of the conversation show the identical card.
 */
const props = withDefaults(defineProps<{
  url: string
  /** Raw markdown link text, e.g. "Pay RM1000 Now". */
  label?: string
  paid?: boolean
  disabled?: boolean
}>(), {
  paid: false,
  disabled: false
})

const amount = computed(() => parsePriceFromLabel(props.label))
const isCompleted = computed(() => props.paid || props.disabled)
</script>

<template>
  <div
    class="group relative overflow-hidden w-fit min-w-[15rem] max-w-[90%] rounded-2xl bg-elevated/40 p-4 sm:p-5"
    :class="isCompleted ? 'border border-emerald-500/30' : ''"
  >
    <!-- Memphis accent: arch, dot and pill in the hero's palette, kept faint so
         it reads as texture behind the amount rather than decoration on top. -->
    <svg
      aria-hidden="true"
      viewBox="0 0 96 96"
      fill="none"
      class="absolute -top-4 -right-3 size-24 opacity-20 dark:opacity-[0.28] pointer-events-none animate-memphis-float"
    >
      <path
        d="M18 62 A 26 26 0 0 1 70 62"
        stroke="currentColor"
        stroke-width="8"
        stroke-linecap="round"
        class="text-primary"
      />
      <circle
        cx="78"
        cy="26"
        r="7"
        fill="currentColor"
        class="text-amber-400"
      />
      <rect
        x="10"
        y="16"
        width="7"
        height="18"
        rx="3.5"
        fill="currentColor"
        class="text-rose-400"
        transform="rotate(-20 13.5 25)"
      />
    </svg>

    <p
      class="relative text-[11px] font-bold uppercase tracking-[0.14em]"
      :class="isCompleted ? 'text-emerald-600 dark:text-emerald-400' : 'text-primary'"
    >
      {{ isCompleted ? ($t('chat.paymentCompleted') || 'Payment Completed') : $t('chat.dealAgreed') }}
    </p>

    <p
      v-if="amount !== null"
      class="relative mt-1 text-2xl sm:text-3xl font-extrabold tracking-tight text-highlighted tabular-nums"
    >
      {{ formatPrice(amount) }}
    </p>
    <p
      v-else
      class="relative mt-1 text-sm text-muted leading-snug"
    >
      {{ isCompleted ? ($t('chat.paymentCompleted') || 'Payment Completed') : $t('chat.completeViaStripe') }}
    </p>

    <!-- Receipt perforation -->
    <div
      aria-hidden="true"
      class="relative my-3.5 border-t border-dashed border-default"
    />

    <UButton
      v-if="isCompleted"
      :disabled="true"
      :label="$t('chat.paymentCompleted') || 'Payment Completed'"
      color="neutral"
      variant="subtle"
      icon="i-lucide-check-circle"
      block
      class="relative font-bold opacity-85 cursor-not-allowed text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 border border-emerald-500/20"
    />
    <UButton
      v-else
      :to="url"
      target="_blank"
      rel="noopener noreferrer"
      :label="amount !== null ? $t('chat.payNow') : (label || $t('chat.payNow'))"
      color="primary"
      icon="i-lucide-arrow-right"
      trailing
      block
      class="relative font-bold transition-transform duration-200 group-hover:scale-[1.01] active:scale-[0.99]"
    />

    <p class="relative mt-4 flex items-center justify-center gap-1.5 text-[11px] text-muted">
      <UIcon
        name="i-lucide-lock"
        class="size-3 shrink-0"
      />
      <span>{{ $t('chat.securedByStripe') }}</span>
      <UIcon
        name="i-nego-stripe-wordmark"
        role="img"
        aria-label="Stripe"
        class="h-3 w-7 shrink-0 text-toned"
      />
    </p>
  </div>
</template>
