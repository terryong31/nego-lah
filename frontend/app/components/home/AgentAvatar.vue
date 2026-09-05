<script setup lang="ts">
/**
 * The bargaining agent's face. Reuses the blue gradient and rounded-square head
 * from the hero's MemphisCharacters bot so the same character shows up in the
 * demo — a drawn friend rather than a stock robot glyph.
 */
</script>

<template>
  <svg
    viewBox="0 0 32 32"
    fill="none"
    class="size-8 select-none"
    aria-hidden="true"
  >
    <defs>
      <linearGradient
        id="agentAvatarGrad"
        x1="0%"
        y1="0%"
        x2="100%"
        y2="100%"
      >
        <stop
          offset="0%"
          stop-color="#60A5FA"
        />
        <stop
          offset="100%"
          stop-color="#3B82F6"
        />
      </linearGradient>
    </defs>

    <!-- Antenna -->
    <path
      d="M16 5V2"
      stroke="#3B82F6"
      stroke-width="2"
      stroke-linecap="round"
    />
    <circle
      cx="16"
      cy="1.8"
      r="1.8"
      fill="#FBBF24"
    />

    <!-- Head -->
    <rect
      x="3"
      y="5"
      width="26"
      height="22"
      rx="8"
      fill="url(#agentAvatarGrad)"
    />

    <!-- Eyes: the left one blinks, so the avatar never reads as a static icon -->
    <circle
      cx="11.5"
      cy="15"
      r="2.6"
      fill="white"
      class="origin-center animate-memphis-pulse-subtle"
    />
    <circle
      cx="20.5"
      cy="15"
      r="2.6"
      fill="white"
    />

    <!-- Grin -->
    <path
      d="M12 21C13.2 22.4 14.5 23 16 23s2.8-.6 4-2"
      stroke="white"
      stroke-width="1.8"
      stroke-linecap="round"
      opacity="0.9"
    />
  </svg>
</template>
