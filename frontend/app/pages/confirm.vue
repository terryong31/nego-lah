<script setup lang="ts">
import type { EmailOtpType } from '@supabase/supabase-js'
import { loginRedirect, safeRedirectPath } from '~/utils/auth'

const { t } = useI18n()
const user = useSupabaseUser()
const supabase = useSupabaseClient()
const route = useRoute()
const router = useRouter()
const { initLanguage } = useLanguage()

type ConfirmStatus = 'loading' | 'success' | 'error'

function getLocalizedError(rawCode?: string | null, rawDesc?: string | null) {
  const code = (rawCode || '').toLowerCase()
  const desc = (rawDesc || '').toLowerCase()

  if (code === 'otp_expired' || desc.includes('expired') || desc.includes('invalid')) {
    return t('auth.linkExpired')
  }
  if (desc) {
    return t('auth.confirmFailedDesc')
  }
  return null
}

const status = ref<ConfirmStatus>(route.query.error || route.query.error_code ? 'error' : 'loading')
const errorMessage = ref<string | null>(null)
const countdown = ref(5)
let timer: ReturnType<typeof setInterval> | null = null

const targetRedirect = ref<string | null>(null)

function proceedToHome() {
  if (timer) clearInterval(timer)
  if (targetRedirect.value) {
    router.push(targetRedirect.value)
  } else {
    router.push('/')
  }
}

onMounted(async () => {
  const searchParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null
  const hashParams = typeof window !== 'undefined' && window.location.hash ? new URLSearchParams(window.location.hash.replace(/^#/, '')) : null

  targetRedirect.value = safeRedirectPath((route.query.redirect as string) || searchParams?.get('redirect'))

  const err = (route.query.error as string) || searchParams?.get('error') || hashParams?.get('error')
  const errCode = (route.query.error_code as string) || searchParams?.get('error_code') || hashParams?.get('error_code')
  const errDesc = (route.query.error_description as string) || searchParams?.get('error_description') || hashParams?.get('error_description')

  if (err || errCode) {
    status.value = 'error'
    errorMessage.value = getLocalizedError(errCode, errDesc)
    // Clean up address bar
    if (typeof window !== 'undefined' && (window.location.search || window.location.hash)) {
      window.history.replaceState(window.history.state, '', window.location.pathname)
    }
    return
  }

  const code = (route.query.code as string) || searchParams?.get('code') || hashParams?.get('code')
  const tokenHash = (route.query.token_hash as string) || searchParams?.get('token_hash') || hashParams?.get('token_hash')
  const type = ((route.query.type as string) || searchParams?.get('type') || hashParams?.get('type') || 'email') as EmailOtpType

  if (code) {
    try {
      const { data, error } = await supabase.auth.exchangeCodeForSession(code)
      if (!error && data?.session) {
        status.value = 'success'
        await initLanguage()
      } else {
        const { data: sessionData } = await supabase.auth.getSession()
        if (sessionData?.session || user.value) {
          status.value = 'success'
          await initLanguage()
        } else {
          status.value = 'error'
        }
      }
    } catch {
      const { data: sessionData } = await supabase.auth.getSession()
      status.value = (sessionData?.session || user.value) ? 'success' : 'error'
    }
  } else if (tokenHash) {
    try {
      const { data, error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type })
      if (!error && data?.session) {
        status.value = 'success'
        await initLanguage()
      } else {
        const { data: sessionData } = await supabase.auth.getSession()
        if (sessionData?.session || user.value) {
          status.value = 'success'
          await initLanguage()
        } else {
          status.value = 'error'
        }
      }
    } catch {
      const { data: sessionData } = await supabase.auth.getSession()
      status.value = (sessionData?.session || user.value) ? 'success' : 'error'
    }
  } else {
    const { data: sessionData } = await supabase.auth.getSession()
    if (sessionData?.session || user.value) {
      status.value = 'success'
    } else {
      setTimeout(async () => {
        const { data: sData } = await supabase.auth.getSession()
        if (sData?.session || user.value) {
          status.value = 'success'
        } else {
          status.value = 'error'
        }
      }, 1500)
    }
  }

  // Clean query params and hash from address bar
  if (typeof window !== 'undefined' && (window.location.search || window.location.hash)) {
    window.history.replaceState(window.history.state, '', window.location.pathname)
  }
})

function startCountdown() {
  if (timer) return
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      proceedToHome()
    }
  }, 1000)
}

watch(user, (newUser) => {
  if (newUser && status.value !== 'error') {
    status.value = 'success'
    startCountdown()
  }
}, { immediate: true })

watch(status, (newStatus) => {
  if (newStatus === 'success') {
    startCountdown()
  }
}, { immediate: true })

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] p-4 text-center">
    <!-- Loading State -->
    <div
      v-if="status === 'loading'"
      class="flex flex-col items-center gap-4"
    >
      <UProgress
        indeterminate
        class="w-64"
      />
      <p class="text-sm text-muted">
        {{ $t('auth.confirmingDesc') }}
      </p>
    </div>

    <!-- Success State: Email Confirmed Screen -->
    <div
      v-else-if="status === 'success'"
      class="max-w-md w-full"
    >
      <UEmpty
        icon="i-lucide-badge-check"
        :title="$t('auth.emailConfirmedTitle')"
        :description="$t('auth.emailConfirmedDesc')"
        variant="naked"
        class="py-8"
      >
        <template #leading>
          <UIcon
            name="i-lucide-badge-check"
            class="size-16 text-success mb-2"
          />
        </template>
        <template #actions>
          <div class="flex flex-col items-center gap-3 w-full">
            <UButton
              :label="$t('auth.continueToStore')"
              color="primary"
              size="lg"
              class="w-full justify-center"
              @click="proceedToHome"
            />
            <p class="text-xs text-muted">
              {{ $t('auth.redirectingCountdown', { seconds: countdown }) }}
            </p>
          </div>
        </template>
      </UEmpty>
    </div>

    <!-- Error State -->
    <div
      v-else
      class="max-w-md w-full"
    >
      <UEmpty
        icon="i-lucide-alert-circle"
        :title="$t('auth.confirmFailedTitle')"
        :description="errorMessage || $t('auth.confirmFailedDesc')"
        variant="naked"
        class="py-8"
        :actions="[{
          label: $t('auth.backToLogin'),
          to: loginRedirect(targetRedirect),
          color: 'neutral',
          size: 'lg'
        }]"
      >
        <template #leading>
          <UIcon
            name="i-lucide-alert-circle"
            class="size-16 text-error mb-2"
          />
        </template>
      </UEmpty>
    </div>
  </div>
</template>
