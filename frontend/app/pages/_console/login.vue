<script setup lang="ts">
definePageMeta({ layout: false })
useSeoMeta({ title: 'Admin', robots: 'noindex, nofollow' })

const { call } = useAdminApi()
const toast = useToast()

const step = ref<'password' | 'otp'>('password')
const email = ref('')
const password = ref('')
const code = ref<string[]>([])
const handle = ref('')
const loading = ref(false)

async function submitPassword() {
  if (!email.value || !password.value) return
  loading.value = true
  try {
    const res = await call<{ handle: string, message: string }>('/auth/login', {
      method: 'POST',
      body: { email: email.value, password: password.value }
    })
    handle.value = res.handle
    step.value = 'otp'
    toast.add({ title: 'Check your email', description: res.message, color: 'info' })
  } catch (err) {
    const e = err as { data?: { detail?: string } }
    toast.add({ title: 'Login failed', description: e.data?.detail || 'Invalid credentials', color: 'error' })
  } finally {
    loading.value = false
  }
}

const OTP_LENGTH = 6

async function submitOtp() {
  if (code.value.length < OTP_LENGTH) return
  loading.value = true
  try {
    await call('/auth/verify-2fa', {
      method: 'POST',
      body: { handle: handle.value, code: code.value.join('') }
    })
    toast.add({ title: 'Welcome back', color: 'success' })
    await navigateTo('/_console')
  } catch (err) {
    const e = err as { data?: { detail?: string } }
    toast.add({ title: 'Verification failed', description: e.data?.detail || 'Invalid or expired code', color: 'error' })
    code.value = []
  } finally {
    loading.value = false
  }
}

function back() {
  step.value = 'password'
  code.value = []
  password.value = ''
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center p-4 bg-muted/30">
    <UCard class="w-full max-w-sm">
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon
            name="i-lucide-shield-check"
            class="size-5 text-primary"
          />
          <h1 class="font-semibold text-highlighted">
            Admin Console
          </h1>
        </div>
      </template>

      <!-- Factor 1: password -->
      <form
        v-if="step === 'password'"
        class="space-y-4"
        @submit.prevent="submitPassword"
      >
        <UFormField label="Email">
          <UInput
            v-model="email"
            type="email"
            autocomplete="username"
            placeholder="you@example.com"
            icon="i-lucide-mail"
            class="w-full"
            :disabled="loading"
          />
        </UFormField>
        <UFormField label="Password">
          <UInput
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            icon="i-lucide-lock"
            class="w-full"
            :disabled="loading"
          />
        </UFormField>
        <UButton
          type="submit"
          block
          label="Continue"
          :loading="loading"
          :disabled="!email || !password"
        />
      </form>

      <!-- Factor 2: email OTP -->
      <form
        v-else
        class="space-y-4"
        @submit.prevent="submitOtp"
      >
        <p class="text-sm text-muted">
          Enter the {{ OTP_LENGTH }}-digit code sent to <span class="font-medium text-highlighted">{{ email }}</span>.
        </p>
        <div class="flex justify-center">
          <UPinInput
            v-model="code"
            :length="OTP_LENGTH"
            otp
            :disabled="loading"
            @complete="submitOtp"
          />
        </div>
        <UButton
          type="submit"
          block
          label="Verify"
          :loading="loading"
          :disabled="code.length < OTP_LENGTH"
        />
        <UButton
          block
          variant="ghost"
          color="neutral"
          label="Back"
          :disabled="loading"
          @click="back"
        />
      </form>
    </UCard>
  </div>
</template>
