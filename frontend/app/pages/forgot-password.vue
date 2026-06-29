<script setup lang="ts">
import * as z from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

const supabase = useSupabaseClient()
const toast = useToast()

useSeoMeta({ title: 'Forgot Password' })

const fields = [{
  name: 'email',
  type: 'email',
  label: 'Email',
  placeholder: 'Enter your email',
  required: true
}]

const schema = z.object({
  email: z.string().email('Invalid email address')
})

type Schema = z.output<typeof schema>
const loading = ref(false)
const sent = ref(false)

async function onSubmit(payload: FormSubmitEvent<Schema>) {
  loading.value = true
  try {
    const { error } = await supabase.auth.resetPasswordForEmail(payload.data.email, {
      redirectTo: `${window.location.origin}/reset-password`
    })
    if (error) throw error
    sent.value = true
    toast.add({ title: 'Check your inbox', description: 'We sent you a password reset link.', color: 'success' })
  } catch (err) {
    toast.add({ title: 'Request failed', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[70vh] gap-4 p-4">
    <UCard class="w-full max-w-md">
      <div
        v-if="sent"
        class="flex flex-col items-center text-center gap-3 py-4"
      >
        <UIcon
          name="i-lucide-mail-check"
          class="size-10 text-primary"
        />
        <h2 class="text-lg font-semibold text-highlighted">
          Email sent
        </h2>
        <p class="text-sm text-muted">
          If an account exists for that email, you'll receive a link to reset your password.
        </p>
        <UButton
          to="/login"
          label="Back to login"
          variant="ghost"
          class="mt-2"
        />
      </div>

      <UAuthForm
        v-else
        :schema="schema"
        title="Forgot password"
        description="Enter your email and we'll send you a reset link."
        icon="i-lucide-key-round"
        :fields="fields"
        :loading="loading"
        :submit="{ label: 'Send reset link' }"
        @submit="onSubmit"
      >
        <template #footer>
          <div class="text-sm text-center text-muted">
            Remembered it?
            <ULink
              to="/login"
              class="text-primary font-medium"
            >Login</ULink>
          </div>
        </template>
      </UAuthForm>
    </UCard>
  </div>
</template>
