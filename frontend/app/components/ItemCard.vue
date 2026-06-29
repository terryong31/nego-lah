<script setup lang="ts">
interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string // JSON array string or comma separated URLs
  price?: number
  min_price?: number
  status?: string // 'available' or 'sold' or other properties
}

const props = withDefaults(defineProps<{
  item?: Item
  loading?: boolean
}>(), {
  loading: false
})

const imageUrl = computed(() => {
  const item = props.item
  if (!item || !item.images) return '/placeholder.png'
  try {
    const parsed = JSON.parse(item.images)
    if (Array.isArray(parsed) && parsed.length > 0) return parsed[0]
  } catch {
    const split = item.images.split(',')
    if (split.length > 0 && split[0]) return split[0].trim()
  }
  return item.images
})
</script>

<template>
  <div
    v-if="loading"
    class="flex flex-col gap-3 p-3 border border-default rounded-xl"
  >
    <USkeleton class="h-48 w-full rounded-lg" />
    <USkeleton class="h-6 w-3/4 rounded" />
    <div class="flex gap-2">
      <USkeleton class="h-5 w-16 rounded-full" />
      <USkeleton class="h-5 w-20 rounded-full" />
    </div>
    <div class="flex justify-between items-center mt-2">
      <USkeleton class="h-8 w-24 rounded" />
      <USkeleton class="h-8 w-8 rounded-full" />
    </div>
  </div>

  <UCard
    v-else-if="item"
    class="group cursor-pointer transition-all duration-300 flex flex-col overflow-hidden"
    :ui="{ body: 'p-0 flex flex-col flex-1', footer: 'p-3 flex justify-between items-center' }"
    @click="navigateTo(`/items/${item.item_id}`)"
  >
    <div class="relative overflow-hidden bg-muted">
      <img
        :src="imageUrl"
        :alt="item.name"
        class="w-full h-auto object-contain group-hover:scale-105 transition-transform duration-500"
      >
      <div class="absolute top-2 right-2 flex flex-col gap-1 items-end">
        <UBadge
          v-if="item.status === 'sold'"
          color="neutral"
          variant="solid"
          size="sm"
        >
          Sold
        </UBadge>
      </div>
    </div>

    <div class="pt-3 flex flex-col gap-1.5 flex-1">
      <h3 class="font-semibold text-base line-clamp-1 group-hover:text-primary transition-colors">
        {{ item.name }}
      </h3>
      <p class="text-sm text-muted line-clamp-2 min-h-[2.5rem]">
        {{ item.condition }}
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col">
        <span class="text-xs text-muted">Price</span>
        <span class="font-bold text-lg text-highlighted">
          RM {{ item.price?.toFixed(2) || '0.00' }}
        </span>
      </div>
      <UButton
        icon="i-lucide-arrow-right"
        size="sm"
        color="neutral"
        variant="ghost"
        class="group-hover:translate-x-1 transition-transform"
      />
    </template>
  </UCard>
</template>
