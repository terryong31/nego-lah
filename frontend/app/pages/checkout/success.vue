<script setup lang="ts">
import { resolveUserId } from '~/utils/auth'

const { call } = useApi()
const route = useRoute()
const { user } = useAuth()
const toast = useToast()
const { t } = useI18n()

// Same palette as the landing hero's dotted matrix.
const DOT_COLORS = [
  'bg-primary', 'bg-amber-400', 'bg-rose-400',
  'bg-purple-400', 'bg-sky-400', 'bg-primary',
  'bg-amber-400', 'bg-rose-400', 'bg-purple-400'
]

const confirming = ref(true)
const success = ref(false)
const refunded = ref(false)
const errorMessage = ref('')
const orderId = ref('')

const chatUrl = computed(() => {
  const itemId = route.query.item_id as string
  return itemId ? `/chat?item_id=${itemId}` : '/chat'
})

// Map a backend outcome to the right UI state. `refunded` = this buyer lost a
// race (someone paid for the 1-of-1 item first) and was auto-refunded.
function applyOutcome(status?: string) {
  if (status === 'refunded') {
    refunded.value = true
    toast.add({
      title: t('checkout.unavailableTitle'),
      description: t('checkout.unavailableDesc'),
      color: 'warning'
    })
  } else {
    // No toast here: the screen itself already shows "Purchase Successful!",
    // so a duplicate toast would be redundant.
    success.value = true
  }
}

onMounted(async () => {
  const itemId = route.query.item_id as string
  const sessionId = route.query.session_id as string | undefined

  if (!itemId) {
    errorMessage.value = t('checkout.missingItem')
    confirming.value = false
    return
  }

  // --- Strategy ---
  // 1. With a session_id, the backend verifies with Stripe and returns a
  //    definitive outcome ('success' | 'already_sold' | 'refunded').
  // 2. Without one (rare fallback), poll THIS user's orders for the item — the
  //    order status (refunded vs not) tells us if they won or lost the race.
  //    Checking the item's own status is not enough: for the loser it shows
  //    'sold' (to the winner), which would look like success.

  if (sessionId) {
    try {
      const res = await call<{ status?: string, order_id?: string }>('/payment/confirm-payment', {
        method: 'POST',
        query: { item_id: itemId, user_id: resolveUserId(user.value), session_id: sessionId }
      })
      orderId.value = res?.order_id || ''
      applyOutcome(res?.status)
    } catch (err) {
      const e = err as { data?: { detail?: string, status?: string }, message?: string }
      // Webhook got there first and returned an already-sold success.
      if (e?.data?.detail?.includes?.('already_sold') || e?.data?.status === 'already_sold') {
        applyOutcome('already_sold')
      } else {
        errorMessage.value = e?.data?.detail || e?.message || t('checkout.confirmFailed')
        toast.add({ title: t('checkout.confirmFailedTitle'), description: errorMessage.value, color: 'error' })
      }
    } finally {
      confirming.value = false
    }
  } else {
    // PaymentLink fallback with no session_id: poll this user's orders.
    let outcome: string | null = null
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const data = await call<{ orders?: Array<{ id?: string, item_id?: string, status?: string }> }>(
          `/payment/orders/user/${resolveUserId(user.value)}`
        )
        const order = data?.orders?.find(o => o.item_id === itemId)
        if (order) {
          orderId.value = order.id || ''
          outcome = order.status === 'refunded' ? 'refunded' : 'success'
          break
        }
      } catch {
        // keep trying
      }
      await new Promise(r => setTimeout(r, 2000))
    }

    if (outcome) {
      applyOutcome(outcome)
    } else {
      // Last resort: ask the backend (it can confirm if the webhook landed).
      try {
        const res = await call<{ status?: string, order_id?: string }>('/payment/confirm-payment', {
          method: 'POST',
          query: { item_id: itemId, user_id: resolveUserId(user.value) }
        })
        if (res?.status === 'already_sold' || res?.status === 'success') {
          orderId.value = res?.order_id || ''
          applyOutcome(res?.status)
        } else {
          errorMessage.value = t('checkout.notConfirmedYet')
          toast.add({ title: t('checkout.pendingTitle'), description: t('checkout.pendingToastDesc'), color: 'warning' })
        }
      } catch {
        errorMessage.value = t('checkout.notVerified')
        toast.add({ title: t('checkout.pendingTitle'), description: t('checkout.pendingToastDesc'), color: 'warning' })
      }
    }
    confirming.value = false
  }
})
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[70vh] px-4 py-10">
    <!-- One card, four moods. The illustrated scene carries the state; the copy
         stays quiet underneath it, and exactly one filled button per view. -->
    <div class="relative w-full max-w-md overflow-hidden rounded-3xl border border-default bg-elevated/30">
      <!-- Scene band: a tinted strip the mark sits in, with a dotted matrix
           bleeding out of the corner the way the hero's accents do. -->
      <div
        class="relative flex justify-center px-6 pt-10 pb-8"
        :class="refunded ? 'bg-warning/5' : errorMessage ? 'bg-error/5' : 'bg-primary/5'"
      >
        <!-- The hero's dotted matrix, kept for the celebratory state only -->
        <div
          v-if="success"
          aria-hidden="true"
          class="absolute top-5 left-5 grid grid-cols-3 gap-1.5 opacity-60 dark:opacity-40 animate-memphis-pulse-subtle"
        >
          <div
            v-for="(dot, i) in DOT_COLORS"
            :key="i"
            class="size-1.5 rounded-full"
            :class="dot"
          />
        </div>

        <CheckoutStatusScene
          :variant="confirming ? 'pending' : refunded ? 'refunded' : success ? 'success' : 'error'"
        />
      </div>

      <div class="px-6 sm:px-8 pt-7 pb-8 text-center">
        <!-- Verifying -->
        <template v-if="confirming">
          <h1 class="text-2xl font-extrabold tracking-tight text-highlighted text-balance">
            {{ $t('checkout.verifyingTitle') }}
          </h1>
          <p class="mt-2 text-sm text-muted leading-relaxed text-pretty">
            {{ $t('checkout.verifyingDesc') }}
          </p>
        </template>

        <!-- Confirmed -->
        <template v-else-if="success">
          <h1 class="text-3xl font-extrabold tracking-tight text-highlighted text-balance">
            {{ $t('checkout.successTitle') }}
          </h1>
          <p class="mt-2 text-sm text-muted leading-relaxed text-pretty">
            {{ $t('checkout.successDesc') }}
          </p>

          <!-- Receipt stub: the same perforation the chat's pay card uses, so
               the hand-off and its receipt read as two halves of one ticket. -->
          <div
            v-if="orderId"
            class="mt-6 border-t border-dashed border-default pt-4 flex items-baseline justify-center gap-2"
          >
            <span class="text-[11px] uppercase tracking-[0.14em] text-muted">
              {{ $t('checkout.orderRef') }}
            </span>
            <span class="font-mono text-xs text-toned">{{ orderId }}</span>
          </div>

          <div class="mt-7 flex flex-col gap-2">
            <UButton
              :to="chatUrl"
              :label="$t('checkout.goToChat')"
              color="primary"
              icon="i-lucide-message-square"
              size="lg"
              block
              class="font-bold"
            />
            <UButton
              :to="'/orders'"
              :label="$t('checkout.viewOrders')"
              color="neutral"
              variant="ghost"
              block
            />
          </div>
        </template>

        <!-- Lost the race, auto-refunded -->
        <template v-else-if="refunded">
          <h1 class="text-2xl font-extrabold tracking-tight text-highlighted text-balance">
            {{ $t('checkout.refundedTitle') }}
          </h1>
          <p class="mt-2 text-sm text-muted leading-relaxed text-pretty">
            {{ $t('checkout.refundedDesc') }}
          </p>
          <div class="mt-7 flex flex-col gap-2">
            <UButton
              to="/"
              :label="$t('checkout.browseOther')"
              color="primary"
              size="lg"
              block
              class="font-bold"
            />
            <UButton
              to="/orders"
              :label="$t('checkout.viewOrders')"
              color="neutral"
              variant="ghost"
              block
            />
          </div>
        </template>

        <!-- Could not verify -->
        <template v-else>
          <h1 class="text-2xl font-extrabold tracking-tight text-highlighted text-balance">
            {{ $t('checkout.errorTitle') }}
          </h1>
          <p class="mt-2 text-sm text-muted leading-relaxed text-pretty break-words">
            {{ errorMessage }}
          </p>
          <p class="mt-3 text-xs text-dimmed leading-relaxed text-pretty">
            {{ $t('checkout.errorSupport') }}
          </p>
          <div class="mt-7 flex flex-col gap-2">
            <UButton
              to="/orders"
              :label="$t('checkout.viewOrders')"
              color="primary"
              size="lg"
              block
              class="font-bold"
            />
            <UButton
              to="/"
              :label="$t('checkout.backStorefront')"
              color="neutral"
              variant="ghost"
              block
            />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
