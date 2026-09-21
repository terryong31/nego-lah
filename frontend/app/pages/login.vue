<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import { loginSchema, type LoginForm } from '~/utils/schemas'
import { safeRedirectPath } from '~/utils/auth'

const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const { call } = useApi()
const { initLanguage } = useLanguage()
const { user, login, signInWithProvider } = useAuth()

const route = useRoute()
const loading = ref(false)

// Where to land after signing in. `?redirect=` is set by `middleware/auth`, the
// `useApi` 401 bounce and the chat send guard — every bounce to this page goes
// through `loginRedirect`, so there is one spelling to read back.
//
// (There used to be a second source: the cookie `@nuxtjs/supabase`'s own guard
// wrote, because that guard ran before ours and had no way to attach a query.
// With the module gone, `middleware/auth` is the only guard there is.)
function getSafeRedirect(): string {
  return safeRedirectPath(route.query.redirect) ?? '/'
}

watch(user, (val) => {
  if (val && !loading.value) {
    router.replace(getSafeRedirect())
  }
}, { immediate: true })

onMounted(() => {
  // `plugins/auth.client.ts` has already asked the server, so `user` is settled
  // by the time this runs — no second session probe to race it.
  if (user.value && !loading.value) {
    router.replace(getSafeRedirect())
  }
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
  onClick: () => {
    // A full navigation to the API, which owns the PKCE exchange and hands the
    // browser back with a session cookie. No authorization code ever reaches
    // this tab, so there is nothing here for a script to intercept (SPEC-093).
    signInWithProvider('google', getSafeRedirect())
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
    const signedIn = await login(payload.data.email, payload.data.password, turnstileToken.value)

    // Block banned users: probe a protected endpoint. A banned account gets a
    // 403, and useApi already signs the user out + shows a toast, so we just
    // stop here. Other (transient) errors shouldn't block a valid login.
    try {
      await call(`/user/${signedIn.id}/account`)
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
    // The server answers every bad credential the same way, on purpose, so the
    // detail is safe to surface as-is.
    const detail = (err as { data?: { detail?: string } })?.data?.detail
    toast.add({
      title: 'Login failed',
      description: detail || (err instanceof Error ? err.message : 'Something went wrong'),
      color: 'error'
    })
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
