<script setup lang="ts">
import { computed, ref } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  type ChartData,
  type ChartOptions
} from 'chart.js'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

interface OrderItem {
  id: string
  amount: number
  created_at: string
  status?: string
}

const props = withDefaults(defineProps<{
  orders?: OrderItem[]
  pending?: boolean
}>(), {
  orders: () => [],
  pending: false
})

const colorMode = useColorMode()
const isDark = computed(() => colorMode.value === 'dark')

const timeframes = [
  { label: '7D', days: 7 },
  { label: '30D', days: 30 },
  { label: 'All', days: 0 }
]
const activeTimeframe = ref(7)

// Aggregate orders by day
const chartData = computed<ChartData<'line'>>(() => {
  const days = activeTimeframe.value
  const now = new Date()
  const datesMap = new Map<string, { label: string, revenue: number, count: number }>()

  const count = days > 0 ? days : 14
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    const key = d.toISOString().split('T')[0] || ''
    const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    datesMap.set(key, { label, revenue: 0, count: 0 })
  }

  // Populate from orders
  for (const o of props.orders) {
    if (!o.created_at) continue
    const key = o.created_at.split('T')[0]
    if (!key) continue
    if (datesMap.has(key)) {
      const entry = datesMap.get(key)!
      entry.revenue += Number(o.amount || 0)
      entry.count += 1
    } else if (days === 0) {
      // For 'All', include any prior dates
      const d = new Date(o.created_at)
      const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      datesMap.set(key, { label, revenue: Number(o.amount || 0), count: 1 })
    }
  }

  const sortedEntries = Array.from(datesMap.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  const labels = sortedEntries.map(e => e[1].label)
  const revenues = sortedEntries.map(e => e[1].revenue)

  return {
    labels,
    datasets: [
      {
        label: 'Revenue (RM)',
        data: revenues,
        fill: true,
        borderColor: '#10b981',
        borderWidth: 2.5,
        backgroundColor: (context) => {
          const ctx = context.chart.ctx
          const gradient = ctx.createLinearGradient(0, 0, 0, 220)
          gradient.addColorStop(0, 'rgba(16, 185, 129, 0.32)')
          gradient.addColorStop(0.85, 'rgba(16, 185, 129, 0.02)')
          gradient.addColorStop(1, 'rgba(16, 185, 129, 0)')
          return gradient
        },
        tension: 0.38,
        pointBackgroundColor: '#10b981',
        pointBorderColor: isDark.value ? '#18181b' : '#ffffff',
        pointBorderWidth: 2,
        pointHoverRadius: 6,
        pointRadius: revenues.some(r => r > 0) ? 3 : 0
      }
    ]
  }
})

const chartOptions = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    mode: 'index',
    intersect: false
  },
  plugins: {
    legend: {
      display: false
    },
    tooltip: {
      backgroundColor: isDark.value ? 'rgba(24, 24, 27, 0.95)' : 'rgba(255, 255, 255, 0.95)',
      titleColor: isDark.value ? '#f4f4f5' : '#18181b',
      bodyColor: isDark.value ? '#a1a1aa' : '#52525b',
      borderColor: isDark.value ? 'rgba(63, 63, 70, 0.5)' : 'rgba(228, 228, 231, 0.8)',
      borderWidth: 1,
      padding: 10,
      boxPadding: 4,
      displayColors: false,
      callbacks: {
        label: (context) => {
          const val = Number(context.raw || 0)
          return `Sales: RM ${val.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        }
      }
    }
  },
  scales: {
    x: {
      grid: {
        display: false
      },
      ticks: {
        color: isDark.value ? '#71717a' : '#a1a1aa',
        font: { size: 12 }
      },
      border: {
        display: false
      }
    },
    y: {
      beginAtZero: true,
      grid: {
        color: isDark.value ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.04)'
      },
      ticks: {
        color: isDark.value ? '#71717a' : '#a1a1aa',
        font: { size: 12 },
        callback: value => `RM ${value}`
      },
      border: {
        display: false
      }
    }
  }
}))
const isCanvasSupported = ref(false)
onMounted(() => {
  try {
    const canvas = document.createElement('canvas')
    isCanvasSupported.value = Boolean(canvas.getContext && canvas.getContext('2d'))
  } catch {
    isCanvasSupported.value = false
  }
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <p class="text-base font-semibold text-highlighted">
          Sales & Revenue Trend
        </p>
        <p class="text-sm text-muted">
          Daily merchandise volume over time
        </p>
      </div>

      <!-- Timeframe Toggle Pills -->
      <div class="flex items-center bg-elevated/70 p-0.5 rounded-lg border border-default text-xs sm:text-sm">
        <button
          v-for="tf in timeframes"
          :key="tf.label"
          type="button"
          class="px-3 py-1 rounded-md transition-all font-medium"
          :class="activeTimeframe === tf.days
            ? 'bg-primary text-primary-foreground shadow-xs'
            : 'text-muted hover:text-highlighted'"
          @click="activeTimeframe = tf.days"
        >
          {{ tf.label }}
        </button>
      </div>
    </div>

    <div class="h-64 relative w-full">
      <div
        v-if="pending"
        class="h-full w-full flex items-center justify-center bg-elevated/30 rounded-lg animate-pulse"
      >
        <UIcon
          name="i-lucide-loader"
          class="size-6 text-muted animate-spin"
        />
      </div>
      <ClientOnly v-else>
        <Line
          v-if="isCanvasSupported"
          :data="chartData"
          :options="chartOptions"
        />
        <div
          v-else
          class="h-full w-full flex items-center justify-center bg-elevated/30 rounded-lg text-xs text-muted"
        >
          Revenue chart visualization
        </div>
        <template #fallback>
          <div class="h-full w-full flex items-center justify-center bg-elevated/30 rounded-lg">
            <UIcon
              name="i-lucide-loader"
              class="size-6 text-muted animate-spin"
            />
          </div>
        </template>
      </ClientOnly>
    </div>
  </div>
</template>
