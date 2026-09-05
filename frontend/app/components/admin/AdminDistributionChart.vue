<script setup lang="ts">
import { computed, ref } from 'vue'
import { Doughnut } from 'vue-chartjs'
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
  type ChartData,
  type ChartOptions
} from 'chart.js'

ChartJS.register(ArcElement, Tooltip, Legend)

const props = withDefaults(defineProps<{
  itemsTotal?: number
  itemsAvailable?: number
  itemsSold?: number
  pending?: boolean
}>(), {
  itemsTotal: undefined,
  itemsAvailable: 0,
  itemsSold: 0,
  pending: false
})

const colorMode = useColorMode()
const isDark = computed(() => colorMode.value === 'dark')

const total = computed(() => props.itemsTotal !== undefined ? props.itemsTotal : (props.itemsAvailable || 0) + (props.itemsSold || 0))

const isCanvasSupported = ref(false)
onMounted(() => {
  try {
    const canvas = document.createElement('canvas')
    isCanvasSupported.value = Boolean(canvas.getContext && canvas.getContext('2d'))
  } catch {
    isCanvasSupported.value = false
  }
})

const chartData = computed<ChartData<'doughnut'>>(() => {
  const available = props.itemsAvailable || 0
  const sold = props.itemsSold || 0

  // If no items yet, show subtle placeholder ring
  if (available === 0 && sold === 0) {
    return {
      labels: ['No listings yet'],
      datasets: [
        {
          data: [1],
          backgroundColor: [isDark.value ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)'],
          borderWidth: 0,
          hoverBackgroundColor: [isDark.value ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)']
        }
      ]
    }
  }

  return {
    labels: ['Available', 'Sold'],
    datasets: [
      {
        data: [available, sold],
        backgroundColor: [
          '#10b981', // emerald-500
          isDark.value ? '#3f3f46' : '#cbd5e1' // zinc-700 or slate-300
        ],
        borderWidth: 2,
        borderColor: isDark.value ? '#18181b' : '#ffffff',
        hoverOffset: 4
      }
    ]
  }
})

const chartOptions = computed<ChartOptions<'doughnut'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  cutout: '72%',
  plugins: {
    legend: {
      display: false
    },
    tooltip: {
      enabled: total.value > 0,
      backgroundColor: isDark.value ? 'rgba(24, 24, 27, 0.95)' : 'rgba(255, 255, 255, 0.95)',
      titleColor: isDark.value ? '#f4f4f5' : '#18181b',
      bodyColor: isDark.value ? '#a1a1aa' : '#52525b',
      borderColor: isDark.value ? 'rgba(63, 63, 70, 0.5)' : 'rgba(228, 228, 231, 0.8)',
      borderWidth: 1,
      padding: 10,
      boxPadding: 4
    }
  }
}))
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <p class="text-base font-semibold text-highlighted">
          Inventory
        </p>
        <p class="text-sm text-muted">
          Active stock vs items sold
        </p>
      </div>
    </div>

    <div class="flex flex-col sm:flex-row items-center gap-6 pt-2">
      <!-- Donut with Center Count -->
      <div class="relative size-44 shrink-0 flex items-center justify-center">
        <ClientOnly>
          <Doughnut
            v-if="isCanvasSupported"
            :data="chartData"
            :options="chartOptions"
          />
          <div
            v-else
            class="size-40 rounded-full border-4 border-default flex items-center justify-center"
          />
          <template #fallback>
            <div class="size-44 rounded-full border-4 border-default animate-pulse" />
          </template>
        </ClientOnly>

        <div class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <USkeleton
            v-if="pending"
            class="h-7 w-12"
          />
          <span
            v-else
            class="text-3xl font-bold text-highlighted leading-none"
          >
            {{ total }}
          </span>
          <span class="text-xs text-muted font-medium mt-1">
            Listings
          </span>
        </div>
      </div>

      <!-- Breakdown Legend -->
      <div class="flex-1 w-full space-y-3">
        <div class="p-3 rounded-lg bg-elevated/40 border border-default flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <div class="size-3 rounded-full bg-emerald-500" />
            <span class="text-sm font-medium text-highlighted">Available</span>
          </div>
          <USkeleton
            v-if="pending"
            class="h-5 w-8"
          />
          <span
            v-else
            class="text-base font-semibold text-success"
          >{{ itemsAvailable }}</span>
        </div>

        <div class="p-3 rounded-lg bg-elevated/40 border border-default flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <div class="size-3 rounded-full bg-zinc-500" />
            <span class="text-sm font-medium text-highlighted">Sold</span>
          </div>
          <USkeleton
            v-if="pending"
            class="h-5 w-8"
          />
          <span
            v-else
            class="text-base font-semibold text-muted"
          >{{ itemsSold }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
