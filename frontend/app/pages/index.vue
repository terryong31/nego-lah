<script setup lang="ts">
import MemphisCharacters from '~/components/hero/MemphisCharacters.vue'
</script>

<template>
  <div class="space-y-20 sm:space-y-28 -mb-6">
    <!-- Corporate Memphis Hero Banner Section -->
    <UHero
      orientation="horizontal"
      :ui="{
        root: 'relative left-1/2 -translate-x-1/2 w-screen -mt-6 min-h-[calc(100dvh-4rem)] lg:min-h-[640px] flex items-center bg-gradient-to-b from-primary/5 via-primary/[0.02] to-transparent overflow-hidden border-b border-default/40',
        container: 'relative z-10 w-full max-w-(--ui-container) mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12 lg:py-[12vw] grid lg:grid-cols-12 gap-8 lg:gap-8 items-center',
        wrapper: 'lg:col-span-6 flex flex-col items-center text-center lg:items-start lg:text-left gap-5 max-w-xl mx-auto lg:mx-0',
        header: 'space-y-4',
        footer: 'mt-0'
      }"
    >
      <template #title>
        <!-- Main Punchy Headline with Memphis wave highlight -->
        <h1 class="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-highlighted leading-[1.15]">
          {{ $t('home.heroTitle1') }}<br>
          {{ $t('home.heroTitle2') }}
          <span class="relative inline-block text-primary">
            {{ $t('home.heroBrand') }}
            <!-- Playful Memphis Wave Underline -->
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
        </h1>
      </template>

      <template #description>
        <!-- Subtitle and playful note with symmetrical spacing -->
        <div class="flex flex-col items-center lg:items-start gap-5">
          <p class="text-base sm:text-lg text-muted leading-relaxed">
            {{ $t('home.heroDesc') }}
          </p>
          <div>
            <UBadge
              color="primary"
              variant="subtle"
              size="md"
            >
              {{ $t('home.heroPs') }}
            </UBadge>
          </div>
        </div>
      </template>

      <template #footer>
        <!-- CTA Button (centered on mobile, left on lg) -->
        <div class="flex flex-wrap items-center justify-center lg:justify-start gap-3 pt-2">
          <UButton
            to="/items"
            size="xl"
            :label="$t('home.browseStuff')"
            trailing-icon="i-lucide-arrow-right"
            class="font-bold shadow-lg hover:shadow-primary/25 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98]"
          />
        </div>
      </template>

      <!-- Right: Large 2D Animated Corporate Memphis Scene -->
      <div class="lg:col-span-6 flex items-center justify-center w-full lg:ml-auto">
        <MemphisCharacters />
      </div>
    </UHero>

    <!-- Product Walkthrough Video Showcase (Screen Studio walkthrough) -->
    <HomeProductVideoShowcase />

    <!-- Terry's promises, in his own voice -->
    <HomeHouseRules />

    <!-- B2B: this system ports to your company -->
    <HomeDeployPitch />
  </div>
</template>
