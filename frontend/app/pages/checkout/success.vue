<script setup lang="ts">
const { call } = useApi()
const route = useRoute()
const user = useSupabaseUser()
const toast = useToast()

const confirming = ref(true)
const success = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  const itemId = route.query.item_id as string
  const sessionId = route.query.session_id as string | undefined

  if (!itemId) {
    errorMessage.value = 'Missing item identifier in confirmation.'
    confirming.value = false
    return
  }

  // --- Strategy ---
  // 1. If we have a session_id (checkout.Session flow), verify with Stripe via backend.
  // 2. If we don't (PaymentLink flow), poll the item status — the webhook should
  //    have already marked it as sold. If not yet, retry a few times.
  // 3. As a final fallback, call confirm-payment (which will verify via Stripe API).

  if (sessionId) {
    // Standard checkout session flow — backend verifies with Stripe
    try {
      await call('/payment/confirm-payment', {
        method: 'POST',
        query: {
          item_id: itemId,
          user_id: user.value?.id,
          session_id: sessionId
        }
      })
      success.value = true
      toast.add({ title: 'Payment confirmed!', description: 'Your order has been recorded successfully.', color: 'success' })
    } catch (err) {
      const e = err as { data?: { detail?: string, status?: string }, message?: string }
      // If already sold, treat as success (webhook got there first)
      if (e?.data?.detail?.includes?.('already_sold') || e?.data?.status === 'already_sold') {
        success.value = true
        toast.add({ title: 'Payment confirmed!', description: 'Your order has been recorded.', color: 'success' })
      } else {
        errorMessage.value = e?.data?.detail || e?.message || 'Payment confirmation failed.'
        toast.add({ title: 'Confirmation failed', description: errorMessage.value, color: 'error' })
      }
    } finally {
      confirming.value = false
    }
  } else {
    // PaymentLink flow — no session_id available.
    // Poll the item to check if the webhook already marked it as sold.
    let sold = false
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const item = await call<{ status?: string }>(`/items/${itemId}`)
        if (item?.status === 'sold') {
          sold = true
          break
        }
      } catch {
        // Item fetch failed, keep trying
      }
      // Wait 2 seconds between polls (webhook may take a moment)
      await new Promise(r => setTimeout(r, 2000))
    }

    if (sold) {
      success.value = true
      toast.add({ title: 'Payment confirmed!', description: 'Your order has been recorded successfully.', color: 'success' })
    } else {
      // Last resort: try the confirm-payment endpoint without session_id
      // This will only work if the backend can verify via other means
      try {
        await call('/payment/confirm-payment', {
          method: 'POST',
          query: {
            item_id: itemId,
            user_id: user.value?.id
          }
        })
        success.value = true
        toast.add({ title: 'Payment confirmed!', description: 'Your order has been recorded.', color: 'success' })
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
