<script setup lang="ts">
import * as z from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

const supabase = useSupabaseClient()
const router = useRouter()
const toast = useToast()

useSeoMeta({ title: 'Reset Password' })

const fields = [{
  name: 'password',
  label: 'New password',
  type: 'password',
  placeholder: 'Enter a new password',
  required: true
}, {
  name: 'confirmPassword',
  label: 'Confirm password',
  type: 'password',
  placeholder: 'Confirm your new password',
  required: true
}]

const schema = z.object({
  password: z.string().min(8, 'Must be at least 8 characters'),
  confirmPassword: z.string().min(8, 'Must be at least 8 characters')
}).refine(data => data.password === data.confirmPassword, {
  message: 'Passwords don\'t match',
  path: ['confirmPassword']
})

type Schema = z.output<typeof schema>
const loading = ref(false)

async function onSubmit(payload: FormSubmitEvent<Schema>) {
  loading.value = true
  try {
    const { error } = await supabase.auth.updateUser({ password: payload.data.password })
    if (error) throw error
    toast.add({ title: 'Password updated', description: 'You can now log in with your new password.', color: 'success' })
    router.push('/login')
  } catch (err) {
    toast.add({ title: 'Update failed', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[70vh] gap-4 p-4">
    <UCard class="w-full max-w-md">
      <UAuthForm
        :schema="schema"
        title="Reset password"
        description="Choose a new password for your account."
        icon="i-lucide-lock"
        :fields="fields"
        :loading="loading"
        :submit="{ label: 'Update password' }"
        @submit="onSubmit"
      />
    </UCard>
  </div>
</template>
