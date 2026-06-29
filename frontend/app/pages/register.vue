<script setup lang="ts">
import * as z from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

const supabase = useSupabaseClient()
const router = useRouter()
const toast = useToast()

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
  placeholder: 'Create a password',
  required: true
}, {
  name: 'confirmPassword',
  label: 'Confirm Password',
  type: 'password',
  placeholder: 'Confirm your password',
  required: true
}]

const schema = z.object({
  email: z.string().email('Invalid email address'),
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
    const { data, error } = await supabase.auth.signUp({
      email: payload.data.email,
      password: payload.data.password
    })
    if (error) throw error

    // Anti-enumeration: when the email already belongs to an account (e.g. one
    // created via Google sign-in), Supabase returns success with NO new identity
    // rather than an error. Detect that and point the user at their real login.
    if (data.user && (data.user.identities?.length ?? 0) === 0) {
      toast.add({
        title: 'Email already registered',
        description: 'This email already has an account. If you signed up with Google, use the Google button.',
        color: 'warning'
      })
      router.push('/login')
      return
    }

    toast.add({ title: 'Registration successful', description: 'Please check your email to verify your account.', color: 'success' })
    router.push('/login')
  } catch (err) {
    toast.add({ title: 'Registration failed', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
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
        title="Register"
        description="Create a new account to start buying and negotiating."
        icon="i-lucide-user-plus"
        :fields="fields"
        :loading="loading"
        @submit="onSubmit"
      >
        <template #footer>
          <div class="text-sm text-center text-muted">
            Already have an account?
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
