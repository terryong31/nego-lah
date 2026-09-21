<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import { resetPasswordSchema, type ResetPasswordForm } from '~/utils/schemas'

const { t } = useI18n()
const { user, resetPassword, logout } = useAuth()
const router = useRouter()
const toast = useToast()

useSeoMeta({ title: () => t('auth.resetPasswordTitle') })

const fields = computed(() => [{
  name: 'password',
  label: t('auth.newPasswordLabel'),
  type: 'password',
  placeholder: t('auth.newPasswordPlaceholder'),
  required: true
}, {
  name: 'confirmPassword',
  label: t('auth.confirmPasswordLabel'),
  type: 'password',
  placeholder: t('auth.confirmPasswordPlaceholder'),
  required: true
}])

const loading = ref(false)

// Arriving here without a session means the link was never followed, or it had
// already been spent. Say so rather than presenting a form whose submit can only
// fail.
const hasRecoverySession = computed(() => Boolean(user.value))

async function onSubmit(payload: FormSubmitEvent<ResetPasswordForm>) {
  loading.value = true
  try {
    await resetPassword(payload.data.password)
    // The password has changed, so every other session for this account should
    // go with it — including this recovery one.
    await logout()
    toast.add({
      title: t('auth.passwordResetSuccess'),
      description: t('auth.passwordResetSuccessDesc'),
      color: 'success'
    })
    router.push('/login')
  } catch (err) {
    const detail = (err as { data?: { detail?: string } })?.data?.detail
    toast.add({
      title: 'Update failed',
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
      <!--
        Arriving without a session means the link was never followed, or it had
        already been spent. Showing the form anyway would present a submit that
        can only fail (SPEC-093).
      -->
      <div
        v-if="!hasRecoverySession"
        class="flex flex-col items-center gap-3 py-6 text-center"
      >
        <UIcon
          name="i-lucide-circle-alert"
          class="size-10 text-error"
        />
        <p class="text-muted">
          {{ $t('auth.linkExpired') }}
        </p>
        <UButton
          to="/forgot-password"
          color="primary"
        >
          {{ $t('auth.forgotPasswordTitle') }}
        </UButton>
      </div>

      <UAuthForm
        v-else
        :schema="resetPasswordSchema"
        :title="$t('auth.resetPasswordTitle')"
        :description="$t('auth.resetPasswordDesc')"
        icon="i-lucide-lock"
        :fields="fields"
        :loading="loading"
        :submit="{ label: $t('common.save') }"
        @submit="onSubmit"
      />
    </UCard>
  </div>
</template>
