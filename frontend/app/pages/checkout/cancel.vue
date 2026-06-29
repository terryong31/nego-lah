<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] text-center p-4">
    <UCard class="w-full max-w-md p-6 space-y-4 flex flex-col items-center">
      <UIcon
        name="i-lucide-alert-circle"
        class="size-16 text-warning"
      />
      <h2 class="text-2xl font-black text-highlighted">
        Payment Cancelled
      </h2>
      <p class="text-sm text-muted">
        Your Stripe transaction was cancelled. No charges were made to your account.
      </p>
      <div class="pt-4 flex gap-4 w-full">
        <UButton
          label="View Items"
          to="/"
          color="primary"
          class="flex-1 justify-center"
        />
      </div>
    </UCard>
  </div>
</template>
