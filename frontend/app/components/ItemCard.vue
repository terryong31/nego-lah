<script setup lang="ts">
import { useItemStore } from '~/stores/item'

interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string // JSON array string or comma separated URLs
  price?: number
  discounted_price?: number
  status?: string // 'available' or 'sold' or other properties
  translations?: Record<string, ItemTranslation>
}

const props = withDefaults(defineProps<{
  item?: Item
  loading?: boolean
}>(), {
  loading: false
})

const { locale } = useI18n()
const itemStore = useItemStore()

const isSold = computed(() => props.item?.status === 'sold')

const displayName = computed(() => localizedItemField(props.item, locale.value, 'name'))
const displayCondition = computed(() => localizedItemField(props.item, locale.value, 'condition'))

// SPEC-041: if this item was already fetched into the store (e.g. the buyer
// negotiated a price mid-chat, in the same tab session), overlay its live
// discounted price so the card reflects it without a fresh fetch — falls
// back to the item prop's own discounted_price otherwise.
const displayItem = computed<Item | undefined>(() => {
  const item = props.item
  if (!item) return item
  const cached = itemStore.getItem(item.item_id)
  if (!cached) return item
  return {
    ...item,
    discounted_price: cached.discountedPrice ?? item.discounted_price
  }
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
    class="flex flex-col gap-3 p-2.5 sm:p-3 border border-default rounded-xl"
  >
    <USkeleton class="aspect-square w-full rounded-lg" />
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
    class="group cursor-pointer transition-all duration-300 flex flex-col overflow-hidden h-full"
    :ui="{ body: 'p-2.5 sm:p-3 flex flex-col flex-1 gap-2.5 sm:gap-3', footer: 'p-2.5 sm:p-3 flex justify-between items-center gap-2' }"
    @click="navigateTo(`/items/${item.item_id}`)"
  >
    <div class="relative overflow-hidden rounded-lg bg-muted aspect-square w-full">
      <img
        :src="imageUrl"
        :alt="displayName"
        class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
        :class="isSold && 'grayscale opacity-60'"
      >
      <div class="absolute top-2 right-2 flex flex-col gap-1 items-end">
        <UBadge
          v-if="isSold"
          color="neutral"
          variant="solid"
          size="lg"
        >
          {{ $t('items.status.sold') }}
        </UBadge>
      </div>
    </div>

    <div class="flex flex-col gap-1 sm:gap-1.5 flex-1">
      <h3 class="font-semibold text-sm sm:text-base line-clamp-2 sm:line-clamp-1 group-hover:text-primary transition-colors">
        {{ displayName }}
      </h3>
      <p class="text-xs sm:text-sm text-muted line-clamp-2 min-h-[2rem] sm:min-h-[2.5rem]">
        {{ displayCondition }}
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col min-w-0">
        <span class="text-xs text-muted">{{ $t('items.price') }}</span>
        <div
          v-if="hasDiscount(displayItem)"
          class="flex flex-wrap items-baseline gap-x-1.5"
        >
          <span class="font-bold text-base sm:text-lg text-primary">
            {{ formatPrice(effectivePrice(displayItem)) }}
          </span>
          <span class="text-xs line-through text-muted">
            {{ formatPrice(displayItem?.price) }}
          </span>
        </div>
        <span
          v-else
          class="font-bold text-base sm:text-lg text-highlighted"
        >
          {{ formatPrice(displayItem?.price) }}
        </span>
      </div>
      <UButton
        icon="i-lucide-arrow-right"
        size="sm"
        color="neutral"
        variant="ghost"
        class="hidden sm:flex group-hover:translate-x-1 transition-transform"
      />
    </template>
  </UCard>
</template>
