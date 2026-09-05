<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import { forgotPasswordSchema, type ForgotPasswordForm } from '~/utils/schemas'

const { t } = useI18n()
const supabase = useSupabaseClient()
const toast = useToast()

useSeoMeta({ title: () => t('auth.forgotPasswordTitle') })

const fields = computed(() => [{
  name: 'email',
  type: 'email',
  label: t('auth.emailLabel'),
  placeholder: t('auth.emailPlaceholder'),
  required: true
}])

const loading = ref(false)
const sent = ref(false)
const { token: turnstileToken, isEnabled: isTurnstileEnabled } = useTurnstileToken()

async function onSubmit(payload: FormSubmitEvent<ForgotPasswordForm>) {
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
    const { error } = await supabase.auth.resetPasswordForEmail(payload.data.email, {
      redirectTo: `${window.location.origin}/reset-password`,
      captchaToken: turnstileToken.value || undefined
    })
    if (error) throw error
    sent.value = true
    toast.add({
      title: t('auth.checkInbox'),
      description: t('auth.resetLinkSent'),
      color: 'success'
    })
  } catch (err) {
    toast.add({
      title: t('auth.requestFailed'),
      description: err instanceof Error ? err.message : t('profile.somethingWentWrong'),
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
      <div
        v-if="sent"
        class="flex flex-col items-center text-center gap-3 py-4"
      >
        <UIcon
          name="i-lucide-mail-check"
          class="size-10 text-primary"
        />
        <h2 class="text-lg font-semibold text-highlighted">
          {{ $t('auth.emailSent') }}
        </h2>
        <p class="text-sm text-muted">
          {{ $t('auth.emailSentDesc') }}
        </p>
        <UButton
          to="/login"
          :label="$t('auth.backToLogin')"
          variant="ghost"
          class="mt-2"
        />
      </div>

      <UAuthForm
        v-else
        :schema="forgotPasswordSchema"
        :title="$t('auth.forgotPasswordTitle')"
        :description="$t('auth.forgotPasswordDesc')"
        icon="i-lucide-key-round"
        :fields="fields"
        :loading="loading"
        :submit="{ label: $t('auth.sendResetLink') }"
        @submit="onSubmit"
      >
        <template #validation>
          <div
            v-if="isTurnstileEnabled"
            class="flex justify-center my-3 min-h-[65px]"
          >
            <NuxtTurnstile
              v-model="turnstileToken"
              :options="{ action: 'forgot-password' }"
            />
          </div>
        </template>

        <template #footer>
          <div class="text-sm text-center text-muted">
            {{ $t('auth.rememberPassword') }}
            <ULink
              to="/login"
              class="text-primary font-medium"
            >{{ $t('auth.loginTitle') }}</ULink>
          </div>
        </template>
      </UAuthForm>
    </UCard>
  </div>
</template>
