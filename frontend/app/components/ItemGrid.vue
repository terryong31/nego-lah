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

defineProps<{
  items: Item[]
  loading?: boolean
}>()
</script>

<template>
  <div>
    <!-- Loading State -->
    <div
      v-if="loading"
      class="columns-1 sm:columns-2 md:columns-3 lg:columns-4 gap-6"
    >
      <ItemCard
        v-for="i in 8"
        :key="i"
        class="mb-6 break-inside-avoid"
        loading
      />
    </div>

    <!-- Empty State -->
    <div
      v-else-if="items.length === 0"
      class="flex flex-col items-center justify-center py-64 px-4"
    >
      <h3 class="text-lg font-semibold text-highlighted">
        No Items Found
      </h3>
      <p class="text-sm text-muted mt-1 text-center max-w-xs">
        Terry Ong has not uploaded anything for sale yet
      </p>
    </div>

    <!-- Grid List -->
    <div
      v-else
      class="columns-1 sm:columns-2 md:columns-3 lg:columns-4 gap-6"
    >
      <ItemCard
        v-for="item in items"
        :key="item.item_id"
        class="mb-6 break-inside-avoid"
        :item="item"
      />
    </div>
  </div>
</template>
