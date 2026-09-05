<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import { resetPasswordSchema, type ResetPasswordForm } from '~/utils/schemas'

const { t } = useI18n()
const supabase = useSupabaseClient()
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

async function onSubmit(payload: FormSubmitEvent<ResetPasswordForm>) {
  loading.value = true
  try {
    const { error } = await supabase.auth.updateUser({ password: payload.data.password })
    if (error) throw error
    toast.add({
      title: t('auth.passwordResetSuccess'),
      description: t('auth.passwordResetSuccessDesc'),
      color: 'success'
    })
    router.push('/login')
  } catch (err) {
    toast.add({
      title: 'Update failed',
      description: err instanceof Error ? err.message : 'Something went wrong',
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
