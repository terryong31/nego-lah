<script setup lang="ts">
/**
 * Terry's three promises, in his own voice.
 *
 * Deliberately not a four-up icon grid. Each rule is anchored by one large
 * hand-drawn Memphis shape — the same vocabulary as the hero's decorations —
 * with the index bleeding off the corner. An earlier pass also carried a lucide
 * icon in the heading; three decorations per card fought each other, so the
 * shape won and the icon went.
 */

const RULES = [
  { id: 'grading', sticker: 'squiggle', accent: 'text-rose-400' },
  { id: 'escrow', sticker: 'arch', accent: 'text-primary' },
  { id: 'local', sticker: 'burst', accent: 'text-amber-400' }
] as const
</script>

<template>
  <section class="reveal-rise">
    <div class="flex flex-col items-center text-center gap-4 mb-10 sm:mb-14">
      <h2 class="text-3xl sm:text-4xl font-extrabold tracking-tight text-highlighted max-w-2xl text-balance">
        {{ $t('home.rules.title') }}
      </h2>
    </div>

    <div class="grid md:grid-cols-3 gap-6 lg:gap-8">
      <article
        v-for="(rule, index) in RULES"
        :key="rule.id"
        class="group relative overflow-hidden rounded-2xl border border-default bg-elevated/25 p-6 sm:p-7 transition-all duration-300 hover:border-primary/40 hover:-translate-y-1"
        :class="index === 1 ? 'md:translate-y-6' : ''"
      >
        <!-- Index, bleeding off the corner -->
        <span
          aria-hidden="true"
          class="absolute -top-8 -right-3 text-[7rem] leading-none font-black text-muted/30 dark:text-muted/20 font-mono select-none pointer-events-none transition-transform duration-500 group-hover:scale-110 group-hover:-rotate-6"
        >
          {{ index + 1 }}
        </span>

        <!-- One large Memphis shape per rule, drawn in its own accent -->
        <svg
          aria-hidden="true"
          viewBox="0 0 64 32"
          fill="none"
          class="relative w-20 h-10 mb-5 overflow-visible"
          :class="rule.accent"
        >
          <path
            v-if="rule.sticker === 'squiggle'"
            d="M3 22 Q 13 2 23 22 T 43 22 T 61 14"
            stroke="currentColor"
            stroke-width="6"
            stroke-linecap="round"
            fill="none"
          />
          <template v-else-if="rule.sticker === 'arch'">
            <path
              d="M5 28 A 19 19 0 0 1 43 28"
              stroke="currentColor"
              stroke-width="6"
              stroke-linecap="round"
              fill="none"
            />
            <circle
              cx="57"
              cy="10"
              r="5"
              fill="currentColor"
              opacity="0.55"
            />
          </template>
          <template v-else>
            <circle
              cx="9"
              cy="16"
              r="8"
              fill="currentColor"
            />
            <rect
              x="26"
              y="6"
              width="19"
              height="19"
              rx="5"
              fill="currentColor"
              opacity="0.55"
            />
            <circle
              cx="57"
              cy="16"
              r="6"
              stroke="currentColor"
              stroke-width="5"
              fill="none"
            />
          </template>
        </svg>

        <h3 class="relative text-lg font-bold text-highlighted mb-2 text-balance">
          {{ $t(`home.rules.items.${rule.id}.title`) }}
        </h3>
        <p class="relative text-sm text-muted leading-relaxed">
          {{ $t(`home.rules.items.${rule.id}.desc`) }}
        </p>
      </article>
    </div>
  </section>
</template>
