<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import { loginSchema, type LoginForm } from '~/utils/schemas'
import { safeRedirectPath } from '~/utils/auth'

const { t } = useI18n()
const supabase = useSupabaseClient()
const router = useRouter()
const toast = useToast()
const { call } = useApi()
const { initLanguage } = useLanguage()

const route = useRoute()
const user = useSupabaseUser()
const loading = ref(false)

// Where to land after signing in. Two sources, in order: our own `?redirect=`
// query (set by `middleware/auth`, the `useApi` 401 bounce and the chat send
// guard), then the cookie @nuxtjs/supabase's own guard writes — Nuxt runs that
// global middleware before any page middleware, so when a session lapses it is
// usually the one that redirects, and `saveRedirectToCookie` (nuxt.config) is
// how it hands the blocked page over. `pluck()` reads and clears in one go, so
// it is called only on the branch that actually navigates.
const cookieRedirect = useSupabaseCookieRedirect()

function getSafeRedirect(): string {
  return safeRedirectPath(route.query.redirect)
    ?? safeRedirectPath(cookieRedirect.pluck())
    ?? '/'
}

watch(user, (val) => {
  if (val && !loading.value) {
    router.replace(getSafeRedirect())
  }
}, { immediate: true })

onMounted(async () => {
  if (user.value && !loading.value) {
    router.replace(getSafeRedirect())
    return
  }
  try {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.user && !loading.value) {
      router.replace(getSafeRedirect())
    }
  } catch { /* ignore */ }
})

const fields = computed(() => [{
  name: 'email',
  type: 'email',
  label: t('auth.emailLabel'),
  placeholder: t('auth.emailPlaceholder'),
  required: true
}, {
  name: 'password',
  label: t('auth.passwordLabel'),
  type: 'password',
  placeholder: t('auth.passwordPlaceholder'),
  required: true
}])

const providers = computed(() => [{
  label: t('auth.googleSignIn'),
  icon: 'i-simple-icons-google',
  onClick: async () => {
    try {
      const safeRedirect = getSafeRedirect()
      const confirmUrl = new URL(`${window.location.origin}/confirm`)
      if (safeRedirect !== '/') {
        confirmUrl.searchParams.set('redirect', safeRedirect)
      }
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: confirmUrl.toString()
        }
      })
      if (error) throw error
    } catch (err) {
      toast.add({ title: 'Auth Error', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
    }
  }
}])

const { token: turnstileToken, isEnabled: isTurnstileEnabled } = useTurnstileToken()

async function onSubmit(payload: FormSubmitEvent<LoginForm>) {
  if (isTurnstileEnabled.value && !turnstileToken.value) {
    toast.add({
      title: t('auth.securityCheckRequired'),
      description: t('auth.securityCheckRequiredDesc'),
      color: 'warning'
    })
    return
  }
  loading.value = true
  try {
    const { data, error } = await supabase.auth.signInWithPassword({
      email: payload.data.email,
      password: payload.data.password,
      options: turnstileToken.value ? { captchaToken: turnstileToken.value } : undefined
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

    // Sync language preference with user metadata
    await initLanguage()

    toast.add({ title: t('auth.loginSuccess'), description: t('auth.loginSuccessDesc'), color: 'success' })
    router.push(getSafeRedirect())
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
        :schema="loginSchema"
        :title="$t('auth.loginTitle')"
        :description="$t('auth.loginDesc')"
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
          >{{ $t('auth.forgotPasswordLink') }}</ULink>
        </template>

        <template #validation>
          <div
            v-if="isTurnstileEnabled"
            class="flex justify-center my-3 min-h-[65px]"
          >
            <NuxtTurnstile
              v-model="turnstileToken"
              :options="{ action: 'login' }"
            />
          </div>
        </template>

        <template #footer>
          <div class="text-sm text-center text-muted">
            {{ $t('auth.noAccount') }}
            <ULink
              :to="route.query.redirect ? { path: '/register', query: { redirect: route.query.redirect } } : '/register'"
              class="text-primary font-medium"
            >{{ $t('auth.registerTitle') }}</ULink>
          </div>
        </template>
      </UAuthForm>
    </UCard>
  </div>
</template>
