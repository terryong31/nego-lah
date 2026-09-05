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
      class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-6"
    >
      <ItemCard
        v-for="i in 8"
        :key="i"
        loading
      />
    </div>

    <!-- Empty State -->
    <UEmpty
      v-else-if="items.length === 0"
      icon="i-lucide-package-open"
      :description="$t('items.emptyGridDesc')"
      variant="naked"
      class="py-24 sm:py-28 lg:py-32"
    >
      <template #title>
        <h3 class="text-lg font-semibold text-highlighted">
          {{ $t('items.noItems') }}
        </h3>
      </template>
    </UEmpty>

    <!-- Grid List -->
    <div
      v-else
      class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-6"
    >
      <ItemCard
        v-for="item in items"
        :key="item.item_id"
        :item="item"
      />
    </div>
  </div>
</template>
