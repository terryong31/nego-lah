<script setup lang="ts">
interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string
  price?: number
  min_price?: number
  status?: string
}

const { call } = useApi()
const route = useRoute()
const router = useRouter()

const searchInput = ref((route.query.keyword as string) || '')
const debouncedSearch = ref((route.query.keyword as string) || '')

// Debounce search input changes
watch(searchInput, (newVal) => {
  const timeout = setTimeout(() => {
    debouncedSearch.value = newVal
    router.replace({ query: { ...route.query, keyword: newVal || undefined } })
  }, 350)
  return () => clearTimeout(timeout)
})

// Sync search input when route query changes (e.g. browser navigation)
watch(() => route.query.keyword, (newVal) => {
  searchInput.value = (newVal as string) || ''
  debouncedSearch.value = (newVal as string) || ''
})

const { data: items, pending } = useAsyncData(
  'items-listing',
  () => {
    const keyword = debouncedSearch.value ? `?keyword=${encodeURIComponent(debouncedSearch.value)}` : ''
    return call<Item[]>(`/items${keyword}`)
  },
  {
    watch: [debouncedSearch],
    default: () => []
  }
)

const activeFilter = ref('all')

const filteredItems = computed(() => {
  if (!items.value) return []
  if (activeFilter.value === 'available') {
    return items.value.filter(item => item.status !== 'sold')
  }
  if (activeFilter.value === 'sold') {
    return items.value.filter(item => item.status === 'sold')
  }
  return items.value
})

useSeoMeta({
  title: 'All Items',
  description: 'Browse all second-hand items and start a bargain session with our AI seller.'
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-col gap-1">
      <h1 class="text-2xl font-bold text-highlighted">
        All Items
      </h1>
      <p class="text-sm text-muted">
        Browse every listing and start a bargain session.
      </p>
    </div>

    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <UInput
        v-model="searchInput"
        icon="i-lucide-search"
        size="md"
        variant="outline"
        placeholder="Search for items..."
        class="w-full sm:w-72"
      />

      <!-- Filter pills -->
      <div class="flex gap-1.5 self-start sm:self-center">
        <UButton
          label="All"
          size="sm"
          :variant="activeFilter === 'all' ? 'solid' : 'ghost'"
          @click="activeFilter = 'all'"
        />
        <UButton
          label="Available"
          size="sm"
          :variant="activeFilter === 'available' ? 'solid' : 'ghost'"
          @click="activeFilter = 'available'"
        />
        <UButton
          label="Sold Out"
          size="sm"
          :variant="activeFilter === 'sold' ? 'solid' : 'ghost'"
          @click="activeFilter = 'sold'"
        />
      </div>
    </div>

    <!-- Item Grid list -->
    <ItemGrid
      :items="filteredItems"
      :loading="pending"
    />
  </div>
</template>
