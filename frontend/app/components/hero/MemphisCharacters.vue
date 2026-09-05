<script setup lang="ts">
// Corporate Memphis / Alegria Scene: Terry with Fender Guitar + AI Bot Companion
// Accents tightly frame the characters at the exact reference positions
</script>

<template>
  <div class="relative w-full max-w-[580px] lg:max-w-[640px] mx-auto select-none pointer-events-none">
    <!-- Ground contact shadow giving natural depth -->
    <div
      class="absolute -bottom-2 left-1/2 -translate-x-1/2 w-4/5 h-8 bg-black/20 dark:bg-black/45 rounded-full blur-xl pointer-events-none"
    />

    <!-- 1. Top-Left: Orange Arch & Pink Dot (directly above Terry's left shoulder & head) -->
    <div class="absolute -top-1 sm:-top-3 left-[10%] sm:left-[12%] z-20 pointer-events-none animate-memphis-float">
      <svg
        width="60"
        height="60"
        viewBox="0 0 70 70"
        fill="none"
        class="w-10 h-10 sm:w-13 sm:h-13 drop-shadow-sm"
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

    <!-- 2. Musical Notes: Floating up from the Red Guitar Headstock -->
    <div
      class="absolute top-[8%] sm:top-[10%] left-[48%] sm:left-[50%] z-20 pointer-events-none animate-memphis-float-reverse select-none flex items-center"
    >
      <span class="text-xl sm:text-2xl font-bold text-pink-500/90 drop-shadow-sm mr-1">♪</span>
      <span class="text-base sm:text-lg font-bold text-purple-400/90 drop-shadow-sm -mt-2">♫</span>
    </div>

    <!-- 3. Top-Right: Rotating 8-Point Yellow Sunburst Star (directly above AI Robot's head) -->
    <div class="absolute top-[4%] sm:top-[6%] right-[12%] sm:right-[15%] z-20 pointer-events-none animate-memphis-spin-slow">
      <svg
        width="48"
        height="48"
        viewBox="0 0 54 54"
        fill="none"
        class="w-9 h-9 sm:w-11 sm:h-11 drop-shadow-sm"
      >
        <path
          d="M27 0L33 18L51 12L39 27L54 39L35 37L27 54L19 37L0 39L15 27L3 12L21 18L27 0Z"
          fill="#FBBF24"
          opacity="0.9"
        />
      </svg>
    </div>

    <!-- 4. Left: Purple Zigzag Ribbon (directly at the side of the electric guitar) -->
    <div
      class="absolute top-[48%] sm:top-[50%] -left-1 sm:left-1 z-20 pointer-events-none opacity-85 animate-memphis-float-reverse select-none"
    >
      <svg
        width="56"
        height="28"
        viewBox="0 0 80 40"
        fill="none"
        class="w-10 h-5 sm:w-13 sm:h-6 drop-shadow-sm"
      >
        <path
          d="M 5 20 L 20 5 L 35 35 L 50 5 L 65 35 L 75 20"
          stroke="#A855F7"
          stroke-width="5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </div>

    <!-- 4. Bottom-Left: Colorful Dotted Matrix (directly under Terry's feet / guitar body) -->
    <div class="hidden sm:block absolute bottom-[3%] sm:bottom-[5%] left-[4%] sm:left-[6%] z-20 pointer-events-none opacity-60 dark:opacity-40 animate-memphis-pulse-subtle">
      <div class="grid grid-cols-4 gap-2 sm:gap-2.5">
        <div class="size-2 rounded-full bg-primary" />
        <div class="size-2 rounded-full bg-amber-400" />
        <div class="size-2 rounded-full bg-rose-400" />
        <div class="size-2 rounded-full bg-purple-400" />
        <div class="size-2 rounded-full bg-sky-400" />
        <div class="size-2 rounded-full bg-primary" />
        <div class="size-2 rounded-full bg-amber-400" />
        <div class="size-2 rounded-full bg-rose-400" />
      </div>
    </div>

    <!-- 5. Bottom-Right: Pastel Turquoise Donut & Confetti Pill (directly in the open space under AI Robot) -->
    <div class="absolute bottom-[4%] sm:bottom-[7%] right-[8%] sm:right-[11%] z-20 pointer-events-none opacity-90 animate-memphis-float">
      <svg
        width="52"
        height="52"
        viewBox="0 0 60 60"
        fill="none"
        class="w-10 h-10 sm:w-12 sm:h-12 drop-shadow-sm"
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

    <!-- Transparent Character Illustration (Zero Background) -->
    <div class="relative z-10 animate-memphis-float">
      <img
        src="/images/hero-illustration.png"
        alt="Terry jamming on guitar alongside AI negotiation assistant"
        width="1200"
        height="896"
        loading="eager"
        fetchpriority="high"
        class="w-full h-auto object-contain drop-shadow-2xl"
      >
    </div>
  </div>
</template>
