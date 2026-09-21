<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import { registerSchema, type RegisterForm } from '~/utils/schemas'
import { loginRedirect } from '~/utils/auth'

const { t } = useI18n()
const { register } = useAuth()
const router = useRouter()
const route = useRoute()
const toast = useToast()

function goToLogin() {
  router.push(loginRedirect(route.query.redirect as string))
}

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
}, {
  name: 'confirmPassword',
  label: t('auth.confirmPasswordLabel'),
  type: 'password',
  placeholder: t('auth.confirmPasswordPlaceholder'),
  required: true
}])

const loading = ref(false)
const { token: turnstileToken, isEnabled: isTurnstileEnabled } = useTurnstileToken()

async function onSubmit(payload: FormSubmitEvent<RegisterForm>) {
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
    await register(payload.data.email, payload.data.password, turnstileToken.value)

    // Anti-enumeration: an address that already has an account gets exactly this
    // response too. The backend decided that (SPEC-093) — it will not tell the
    // caller which case this was, and neither can we, so the copy has to work
    // for both: check your inbox, and if nothing arrives you already have an
    // account.
    toast.add({
      title: t('auth.registerSuccess'),
      description: t('auth.registerSuccessDesc'),
      color: 'success'
    })
    goToLogin()
  } catch (err) {
    const detail = (err as { data?: { detail?: string } })?.data?.detail
    toast.add({
      title: 'Registration failed',
      description: detail || (err instanceof Error ? err.message : 'Something went wrong'),
      color: 'error'
    })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[70vh] gap-4 p-4">
    <UCard class="w-full max-w-md">
      <UAuthForm
        :schema="registerSchema"
        :title="$t('auth.registerTitle')"
        :description="$t('auth.registerDesc')"
        icon="i-lucide-user-plus"
        :fields="fields"
        :loading="loading"
        @submit="onSubmit"
      >
        <template #validation>
          <div
            v-if="isTurnstileEnabled"
            class="flex justify-center my-3 min-h-[65px]"
          >
            <NuxtTurnstile
              v-model="turnstileToken"
              :options="{ action: 'register' }"
            />
          </div>
        </template>

        <template #footer>
          <div class="text-sm text-center text-muted">
            {{ $t('auth.haveAccount') }}
            <ULink
              :to="loginRedirect(route.query.redirect as string)"
              class="text-primary font-medium"
            >{{ $t('auth.loginTitle') }}</ULink>
          </div>
        </template>
      </UAuthForm>
    </UCard>
  </div>
</template>
