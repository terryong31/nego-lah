<script setup lang="ts">
interface Props {
  size?: 'sm' | 'md' | 'lg'
  hideText?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  hideText: false
})

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'sm':
      return {
        icon: 'size-6',
        text: 'text-lg',
        badge: 'text-xs px-1.5 py-0.5'
      }
    case 'lg':
      return {
        icon: 'size-10',
        text: 'text-2xl',
        badge: 'text-sm px-2.5 py-1'
      }
    case 'md':
    default:
      return {
        icon: 'size-8',
        text: 'text-xl',
        badge: 'text-xs px-2 py-0.5'
      }
  }
})
</script>

<template>
  <div class="inline-flex items-center gap-2 select-none group">
    <!-- Brand Mark SVG: Integrated Negotiation Bubble + Fair-Trade Price Tag -->
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      :class="['shrink-0 transition-transform duration-300 group-hover:scale-105', sizeClasses.icon]"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id="logo-grad"
          x1="4"
          y1="4"
          x2="36"
          y2="36"
          gradientUnits="userSpaceOnUse"
        >
          <stop
            offset="0%"
            stop-color="#10b981"
          />
          <stop
            offset="100%"
            stop-color="#059669"
          />
        </linearGradient>
        <linearGradient
          id="logo-accent"
          x1="12"
          y1="12"
          x2="28"
          y2="28"
          gradientUnits="userSpaceOnUse"
        >
          <stop
            offset="0%"
            stop-color="#ffffff"
          />
          <stop
            offset="100%"
            stop-color="#ecfdf5"
          />
        </linearGradient>
      </defs>

      <!-- Outer Squircle Tag with Negotiation Notch -->
      <path
        d="M6 14C6 8.47715 10.4772 4 16 4H26C31.5228 4 36 8.47715 36 14V24C36 29.5228 31.5228 34 26 34H17L10 38V33.4C7.5 31.8 6 28.5 6 24V14Z"
        fill="url(#logo-grad)"
      />

      <!-- Tag Eyelet Circle -->
      <circle
        cx="13"
        cy="11"
        r="2.5"
        fill="#064e3b"
        opacity="0.3"
      />
      <circle
        cx="13"
        cy="11"
        r="1.75"
        fill="#ffffff"
        opacity="0.9"
      />

      <!-- Stylized 'N' & Negotiation Bargain Arrow -->
      <path
        d="M16 26V15L24 25V14"
        stroke="url(#logo-accent)"
        stroke-width="2.75"
        stroke-linecap="round"
        stroke-linejoin="round"
      />

      <!-- Sparkle / Fair-Price Deal Star -->
      <path
        d="M28 10L28.8 12.2L31 13L28.8 13.8L28 16L27.2 13.8L25 13L27.2 12.2L28 10Z"
        fill="#fbbf24"
      />
    </svg>

    <!-- Brand Name Typography -->
    <span
      v-if="!hideText"
      class="inline-flex items-center font-black tracking-tight"
      :class="sizeClasses.text"
    >
      <span class="text-highlighted">Nego</span>
      <span class="text-primary">-lah</span>
    </span>
  </div>
</template>
