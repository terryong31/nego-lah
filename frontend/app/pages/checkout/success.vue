<script setup lang="ts">
const { call } = useApi()
const route = useRoute()
const user = useSupabaseUser()
const toast = useToast()

const confirming = ref(true)
const success = ref(false)
const refunded = ref(false)
const errorMessage = ref('')

// Map a backend outcome to the right UI state. `refunded` = this buyer lost a
// race (someone paid for the 1-of-1 item first) and was auto-refunded.
function applyOutcome(status?: string) {
  if (status === 'refunded') {
    refunded.value = true
    toast.add({
      title: 'Item no longer available',
      description: 'Someone bought it just before your payment. You have been fully refunded.',
      color: 'warning'
    })
  } else {
    success.value = true
    toast.add({ title: 'Payment confirmed!', description: 'Your order has been recorded successfully.', color: 'success' })
  }
}

onMounted(async () => {
  const itemId = route.query.item_id as string
  const sessionId = route.query.session_id as string | undefined

  if (!itemId) {
    errorMessage.value = 'Missing item identifier in confirmation.'
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
      const res = await call<{ status?: string }>('/payment/confirm-payment', {
        method: 'POST',
        query: { item_id: itemId, user_id: user.value?.id, session_id: sessionId }
      })
      applyOutcome(res?.status)
    } catch (err) {
      const e = err as { data?: { detail?: string, status?: string }, message?: string }
      // Webhook got there first and returned an already-sold success.
      if (e?.data?.detail?.includes?.('already_sold') || e?.data?.status === 'already_sold') {
        applyOutcome('already_sold')
      } else {
        errorMessage.value = e?.data?.detail || e?.message || 'Payment confirmation failed.'
        toast.add({ title: 'Confirmation failed', description: errorMessage.value, color: 'error' })
      }
    } finally {
      confirming.value = false
    }
  } else {
    // PaymentLink fallback with no session_id: poll this user's orders.
    let outcome: string | null = null
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const data = await call<{ orders?: Array<{ item_id?: string, status?: string }> }>(
          `/payment/orders/user/${user.value?.id}`
        )
        const order = data?.orders?.find(o => o.item_id === itemId)
        if (order) {
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
        const res = await call<{ status?: string }>('/payment/confirm-payment', {
          method: 'POST',
          query: { item_id: itemId, user_id: user.value?.id }
        })
        if (res?.status === 'already_sold' || res?.status === 'success') {
          applyOutcome(res?.status)
        } else {
          errorMessage.value = 'We could not confirm your payment yet. If you were charged, it will be recorded shortly — check My Orders, or contact support with your Stripe receipt.'
          toast.add({ title: 'Verification pending', description: 'Could not confirm payment automatically.', color: 'warning' })
        }
      } catch {
        errorMessage.value = 'We could not verify your payment automatically. If you were charged, please contact support with your Stripe receipt.'
        toast.add({ title: 'Verification pending', description: 'Could not confirm payment automatically.', color: 'warning' })
      }
    }
    confirming.value = false
  }
})
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] text-center p-4">
    <UCard class="w-full max-w-md p-6">
      <div
        v-if="confirming"
        class="space-y-4 flex flex-col items-center"
      >
        <UProgress
          indeterminate
          class="w-48"
        />
        <h2 class="text-xl font-bold text-highlighted">
          Verifying Transaction
        </h2>
        <p class="text-sm text-muted">
          Please wait while we confirm your payment with Stripe...
        </p>
      </div>

      <div
        v-else-if="success"
        class="space-y-4 flex flex-col items-center"
      >
        <UIcon
          name="i-lucide-check-circle"
          class="size-16 text-success"
        />
        <h2 class="text-2xl font-black text-highlighted">
          Purchase Successful!
        </h2>
        <p class="text-sm text-muted">
          Your payment was confirmed. The seller will fulfill and dispatch your item shortly.
        </p>
        <div class="pt-4 flex gap-4 w-full">
          <UButton
            label="View My Orders"
            to="/orders"
            color="primary"
            class="flex-1 justify-center"
          />
          <UButton
            label="Back to Storefront"
            to="/"
            variant="outline"
            class="flex-1 justify-center"
          />
        </div>
      </div>

      <div
        v-else-if="refunded"
        class="space-y-4 flex flex-col items-center"
      >
        <UIcon
          name="i-lucide-rotate-ccw"
          class="size-16 text-warning"
        />
        <h2 class="text-2xl font-black text-highlighted">
          Item No Longer Available
        </h2>
        <p class="text-sm text-muted">
          Someone completed payment for this one-of-a-kind item moments before you.
          Your payment has been <span class="font-semibold">fully refunded</span> —
          it may take a few days to appear on your statement.
        </p>
        <div class="pt-4 flex gap-4 w-full">
          <UButton
            label="Browse Other Items"
            to="/"
            color="primary"
            class="flex-1 justify-center"
          />
          <UButton
            label="View My Orders"
            to="/orders"
            variant="outline"
            class="flex-1 justify-center"
          />
        </div>
      </div>

      <div
        v-else
        class="space-y-4 flex flex-col items-center"
      >
        <UIcon
          name="i-lucide-x-circle"
          class="size-16 text-danger"
        />
        <h2 class="text-xl font-bold text-highlighted">
          Verification Error
        </h2>
        <p class="text-sm text-muted">
          {{ errorMessage }}
        </p>
        <p class="text-xs text-muted pt-2">
          If you believe this is a mistake, please keep your Stripe receipt and contact support.
        </p>
        <div class="pt-4 w-full">
          <UButton
            label="Back to Storefront"
            to="/"
            color="neutral"
            class="w-full justify-center"
          />
        </div>
      </div>
    </UCard>
  </div>
</template>
