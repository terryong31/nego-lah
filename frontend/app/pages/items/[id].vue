<script setup lang="ts">
import { loginRedirect } from '~/utils/auth'
import { useItemStore } from '~/stores/item'

interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string
  price?: number
  discounted_price?: number
  status?: string
  translations?: Record<string, ItemTranslation>
}

const { call } = useApi()
const route = useRoute()
const toast = useToast()
const { t, locale } = useI18n()
const itemStore = useItemStore()

const id = computed(() => route.params.id as string)

// SPEC-041: fetch through the shared item store (a no-op if the buyer already
// negotiated a price for this item in an earlier chat this tab session — the
// page then shows that cached, already-live price with no extra API call).
// `item` itself is a separate computed reading live store state (below), not
// this async function's return value, so it reflects the freshest cache even
// if that changes after this initial load resolves.
const { pending, error } = useAsyncData(
  `item-detail-${id.value}`,
  async () => {
    await itemStore.fetchIfMissing(id.value)
    const state = itemStore.getItem(id.value)
    if (!state) throw new Error('Item not found')
    return state.item
  }
)

const item = computed<Item | null>(() => {
  const state = itemStore.getItem(id.value)
  if (!state) return null
  return {
    ...state.item,
    discounted_price: state.discountedPrice ?? state.item.discounted_price
  } as Item
})

/** Unconditionally re-fetch, bypassing the store's fetchIfMissing dedup — used
 * when the caller knows the cache may be stale (the 409 "just sold" retry). */
async function refresh() {
  await itemStore.refetch(id.value)
}

const localizedTitle = computed(() => localizedItemField(item.value, locale.value, 'name'))
const localizedCondition = computed(() => localizedItemField(item.value, locale.value, 'condition'))
const localizedDescription = computed(() => localizedItemField(item.value, locale.value, 'description'))

const imagesList = computed<string[]>(() => {
  if (!item.value?.images) return []
  try {
    const parsed = JSON.parse(item.value.images)
    if (Array.isArray(parsed)) return parsed
  } catch {
    const split = item.value.images.split(',')
    if (split.length > 0) return split.map((img: string) => img.trim())
  }
  return [item.value.images]
})

const buyLoading = ref(false)
const user = useSupabaseUser()

async function handleBuyNow() {
  if (!user.value) {
    navigateTo(loginRedirect(route.fullPath))
    return
  }

  buyLoading.value = true
  try {
    const res = await call<{ checkout_url?: string }>('/payment/checkout', {
      method: 'POST',
      body: {
        item_id: id.value,
        user_id: user.value.id
      }
    })

    if (res?.checkout_url) {
      toast.add({ title: t('items.redirectingCheckout'), description: t('items.openingStripe'), color: 'success' })
      window.location.href = res.checkout_url
    } else {
      throw new Error('No checkout URL returned')
    }
  } catch (err) {
    // 409 = the item was sold/reserved between page load and checkout. Refresh
    // so the button flips to the "sold" state, and tell the user plainly.
    const status = (err as { statusCode?: number, status?: number })?.statusCode
      ?? (err as { status?: number })?.status
    if (status === 409) {
      toast.add({ title: t('items.noLongerAvailable'), description: t('items.justSold'), color: 'warning' })
      await refresh()
    } else {
      toast.add({ title: t('items.checkoutFailed'), description: err instanceof Error ? err.message : t('items.unableToStart'), color: 'error' })
    }
  } finally {
    buyLoading.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <div
      v-if="pending"
      class="grid grid-cols-1 md:grid-cols-2 gap-8"
    >
      <USkeleton class="h-96 w-full rounded-xl" />
      <div class="space-y-4">
        <USkeleton class="h-10 w-2/3" />
        <USkeleton class="h-6 w-24 rounded-full" />
        <USkeleton class="h-24 w-full" />
        <USkeleton class="h-12 w-32" />
        <div class="flex gap-4">
          <USkeleton class="h-10 w-32" />
          <USkeleton class="h-10 w-32" />
        </div>
      </div>
    </div>

    <UEmpty
      v-else-if="error || !item"
      icon="i-lucide-alert-triangle"
      :title="$t('items.itemNotFound')"
      :description="$t('items.itemNotFoundDesc')"
      :actions="[{
        label: $t('items.backToStorefront'),
        to: '/'
      }]"
      variant="naked"
      class="py-20"
    />

    <div
      v-else
      class="grid grid-cols-1 md:grid-cols-2 gap-8 md:h-[calc(100vh-12rem)] items-center"
    >
      <!-- Left side: Image Gallery/Carousel — vertically centered -->
      <div class="flex flex-col justify-center h-full">
        <div class="relative">
          <UCarousel
            v-if="imagesList.length > 0"
            v-slot="{ item: img }"
            :items="imagesList"
            :arrows="imagesList.length > 1"
            :dots="imagesList.length > 1"
            prev-icon="i-lucide-chevron-left"
            next-icon="i-lucide-chevron-right"
            loop
            class="w-full"
            :ui="{
              container: 'items-center',
              item: 'basis-full',
              prev: 'start-3 sm:start-3 z-10 bg-white/80 hover:bg-white text-gray-800 shadow',
              next: 'end-3 sm:end-3 z-10 bg-white/80 hover:bg-white text-gray-800 shadow',
              dots: '-bottom-6',
              dot: 'size-2.5 bg-default/30 data-[state=active]:bg-primary'
            }"
          >
            <div class="w-full flex items-center justify-center">
              <img
                :src="img"
                class="max-w-full max-h-[70vh] w-auto h-auto object-contain rounded-xl"
                draggable="false"
              >
            </div>
          </UCarousel>
          <div
            v-else
            class="w-full aspect-[4/3] flex items-center justify-center text-muted rounded-xl overflow-hidden"
          >
            {{ $t('items.noImages') }}
          </div>
        </div>
      </div>

      <!-- Right side: title+price top, compact description, buttons pinned bottom -->
      <div class="flex flex-col h-full py-2 min-h-0">
        <!-- Title + price -->
        <div class="shrink-0 space-y-3">
          <h1 class="text-3xl font-extrabold text-highlighted tracking-tight">
            {{ localizedTitle }}
          </h1>
          <div
            v-if="hasDiscount(item)"
            class="flex items-center gap-3 flex-wrap"
          >
            <span class="text-3xl font-extrabold text-primary tracking-tight">
              {{ formatPrice(effectivePrice(item)) }}
            </span>
            <span class="text-xl line-through text-muted font-medium">
              {{ formatPrice(item.price) }}
            </span>
            <UBadge
              color="primary"
              variant="subtle"
              size="md"
              :label="`-${discountPercent(item)}%`"
            />
          </div>
          <div
            v-else
            class="text-2xl font-extrabold text-highlighted tracking-tight"
          >
            {{ formatPrice(item.price) }}
          </div>
        </div>

        <!-- Compact description: reduced height, scrolls internally only if long -->
        <div class="mt-3 space-y-2 flex-1 min-h-0 flex flex-col">
          <h3 class="font-semibold text-highlighted shrink-0">
            {{ $t('items.productDesc') }}
          </h3>
          <div class="flex items-center gap-2 shrink-0">
            <span class="text-sm text-muted">{{ $t('items.conditionColon') }}</span>
            <span class="text-sm font-semibold capitalize">{{ localizedCondition }}</span>
          </div>
          <div class="text-muted text-sm leading-relaxed flex-1 min-h-0 overflow-y-auto pr-2 pb-4 prose prose-sm dark:prose-invert max-w-none">
            <MDC :value="localizedDescription" />
          </div>
        </div>

        <!-- Pinned bottom: sold alert + action buttons -->
        <div class="mt-auto shrink-0 space-y-4 pt-4 border-t border-default/50">
          <UAlert
            v-if="item.status === 'sold'"
            color="neutral"
            variant="subtle"
            :title="$t('items.itemSold')"
            icon="i-lucide-info"
          />

          <div
            v-if="item.status !== 'sold'"
            class="flex flex-col sm:flex-row gap-4"
          >
            <!-- Buy Now -->
            <UButton
              size="lg"
              color="primary"
              variant="solid"
              class="flex-1 justify-center"
              :loading="buyLoading"
              icon="i-lucide-credit-card"
              @click="handleBuyNow"
            >
              {{ $t('items.buyNow') }}
            </UButton>

            <!-- Bargain / Chat -->
            <UButton
              size="lg"
              color="neutral"
              variant="outline"
              class="flex-1 justify-center"
              icon="i-lucide-message-square"
              :to="user ? `/chat?item_id=${item.item_id}` : loginRedirect(`/chat?item_id=${item.item_id}`)"
            >
              {{ $t('items.negotiatePrice') }}
            </UButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
