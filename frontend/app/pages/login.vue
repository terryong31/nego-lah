<script setup lang="ts">
import * as z from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

const supabase = useSupabaseClient()
const router = useRouter()
const toast = useToast()
const { call } = useApi()

const fields = [{
  name: 'email',
  type: 'email',
  label: 'Email',
  placeholder: 'Enter your email',
  required: true
}, {
  name: 'password',
  label: 'Password',
  type: 'password',
  placeholder: 'Enter your password',
  required: true
}]

const providers = [{
  label: 'Google',
  icon: 'i-simple-icons-google',
  onClick: async () => {
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/confirm`
        }
      })
      if (error) throw error
    } catch (err) {
      toast.add({ title: 'Auth Error', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
    }
  }
}]

const schema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Must be at least 8 characters')
})

type Schema = z.output<typeof schema>
const loading = ref(false)

async function onSubmit(payload: FormSubmitEvent<Schema>) {
  loading.value = true
  try {
    const { data, error } = await supabase.auth.signInWithPassword({
      email: payload.data.email,
      password: payload.data.password
    })
    if (error) throw error

    // Block banned users: probe a protected endpoint. A banned account gets a
    // 403, and useApi already signs the user out + shows a toast, so we just
    // stop here. Other (transient) errors shouldn't block a valid login.
    try {
      await call(`/user/${data.user.id}/account`)
    } catch (probeErr) {
      const e = probeErr as { statusCode?: number, status?: number, data?: { detail?: string } }
      const status = e?.statusCode ?? e?.status
      const detail = String(e?.data?.detail ?? '').toLowerCase()
      if (status === 403 && detail.includes('banned')) return
    }

    toast.add({ title: 'Welcome back!', description: 'You have logged in successfully.', color: 'success' })
    router.push('/')
  } catch (err) {
    toast.add({ title: 'Login failed', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[80vh] gap-4 p-4">
    <UCard class="w-full max-w-md">
      <UAuthForm
        :schema="schema"
        title="Login"
        description="Enter your credentials to access your account."
        icon="i-lucide-user"
        :fields="fields"
        :providers="providers"
        :loading="loading"
        @submit="onSubmit"
      >
        <template #password-hint>
          <ULink
            to="/forgot-password"
            class="text-primary font-medium"
          >Forgot password?</ULink>
        </template>

        <template #footer>
          <div class="text-sm text-center text-muted">
            Don't have an account?
            <ULink
              to="/register"
              class="text-primary font-medium"
            >Register</ULink>
          </div>
        </template>
      </UAuthForm>
    </UCard>
  </div>
</template>
