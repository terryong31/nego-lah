<script setup lang="ts">
import type { FormSubmitEvent } from '@nuxt/ui'
import {
  emailChangeSchema,
  passwordChangeSchema,
  type EmailChangeForm,
  type PasswordChangeForm
} from '~/utils/schemas'
import { resolveAvatarUrl } from '~/utils/auth'

definePageMeta({
  middleware: 'auth'
})

const { t } = useI18n()
const { call } = useApi()
const user = useSupabaseUser()
const supabase = useSupabaseClient()
const router = useRouter()
const toast = useToast()

// General Settings - display name & profile picture (stored in user metadata)
const displayName = ref(user.value?.user_metadata?.display_name || '')
const avatarUrl = ref(resolveAvatarUrl(user.value) || '')
const avatarFile = ref<File | null>(null)
const avatarPreview = ref('')
const profileLoading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const initials = computed(() => {
  const name = displayName.value || user.value?.email || ''
  return name.slice(0, 2).toUpperCase()
})

// Resolve the user id from the live session rather than the reactive
// `useSupabaseUser` ref. The ref can be populated (truthy) while its `id` is
// still undefined during hydration, which produced `/user/undefined/profile`
// requests. The session is the same source `useApi` reads the JWT from, so the
// path id and the Authorization header are guaranteed to refer to the same user.
async function getUserId(): Promise<string | null> {
  const { data: { session } } = await supabase.auth.getSession()
  return session?.user?.id ?? user.value?.id ?? null
}

// Keep local fields in sync if the user object updates elsewhere
watch(user, (u) => {
  displayName.value = u?.user_metadata?.display_name || ''
  avatarUrl.value = resolveAvatarUrl(u) || ''
})

function onAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    toast.add({ title: t('profile.imageTooLarge'), description: t('profile.imageTooLargeDesc'), color: 'error' })
    return
  }
  avatarFile.value = file
  avatarPreview.value = URL.createObjectURL(file)
}

async function onProfileSave() {
  const userId = await getUserId()
  if (!userId) return
  profileLoading.value = true
  try {
    // Everything goes through the backend (service role + JWT). The avatar is
    // uploaded server-side; the client never writes to the storage bucket.
    const form = new FormData()
    form.append('display_name', displayName.value)
    if (avatarFile.value) form.append('avatar', avatarFile.value)

    const res = await call<{ display_name: string | null, avatar_url: string | null }>(
      `/user/${userId}/profile`,
      { method: 'PUT', body: form }
    )

    // Refresh the client session so the updated metadata (used by the header) shows
    await supabase.auth.refreshSession()

    avatarUrl.value = res.avatar_url || avatarUrl.value
    avatarFile.value = null
    avatarPreview.value = ''
    toast.add({ title: t('profile.profileUpdated'), description: t('profile.profileUpdatedDesc'), color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('profile.updateProfileFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    profileLoading.value = false
  }
}

// Change Email
const emailSchema = emailChangeSchema
const emailLoading = ref(false)
// UForm validates against `state`; without it the form never emits `submit`.
const emailState = reactive<{ email: string | undefined }>({ email: undefined })

async function onEmailSubmit(payload: FormSubmitEvent<EmailChangeForm>) {
  const userId = await getUserId()
  if (!userId) return
  emailLoading.value = true
  try {
    await call(`/user/${userId}/email`, {
      method: 'PUT',
      body: {
        new_email: payload.data.email
      }
    })
    emailState.email = undefined
    toast.add({ title: t('profile.emailChangeRequested'), description: t('profile.emailChangeRequestedDesc'), color: 'success' })
  } catch (err) {
    toast.add({ title: t('profile.updateEmailFailed'), description: err instanceof Error ? err.message : t('profile.somethingWentWrong'), color: 'error' })
  } finally {
    emailLoading.value = false
  }
}

// Change Password
const passwordSchema = passwordChangeSchema
const passwordLoading = ref(false)
// UForm validates against `state`; without it the form never emits `submit`.
const passwordState = reactive<{ currentPassword: string | undefined, newPassword: string | undefined, confirmPassword: string | undefined }>({
  currentPassword: undefined,
  newPassword: undefined,
  confirmPassword: undefined
})

async function onPasswordSubmit(payload: FormSubmitEvent<PasswordChangeForm>) {
  const userId = await getUserId()
  if (!userId) return
  passwordLoading.value = true
  try {
    await call(`/user/${userId}/password`, {
      method: 'PUT',
      body: {
        current_password: payload.data.currentPassword,
        new_password: payload.data.newPassword
      }
    })
    passwordState.currentPassword = undefined
    passwordState.newPassword = undefined
    passwordState.confirmPassword = undefined
    toast.add({ title: t('profile.passwordUpdated'), description: t('profile.passwordUpdatedDesc'), color: 'success' })
  } catch (err) {
    toast.add({ title: t('profile.updatePasswordFailed'), description: err instanceof Error ? err.message : t('profile.somethingWentWrong'), color: 'error' })
  } finally {
    passwordLoading.value = false
  }
}

// Danger Zone - Account Deletion
const deleteModalOpen = ref(false)
const deleteLoading = ref(false)

async function handleDeleteAccount() {
  const userId = await getUserId()
  if (!userId) return
  deleteLoading.value = true
  try {
    await call(`/user/${userId}`, { method: 'DELETE' })
    await supabase.auth.signOut()
    toast.add({ title: t('profile.accountDeleted'), description: t('profile.accountDeletedDesc'), color: 'success' })
    router.push('/')
  } catch (err) {
    toast.add({ title: t('profile.deleteAccountFailed'), description: err instanceof Error ? err.message : t('profile.somethingWentWrong'), color: 'error' })
  } finally {
    deleteLoading.value = false
    deleteModalOpen.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto space-y-8">
    <div>
      <h1 class="text-2xl font-bold text-highlighted">
        {{ $t('profile.title') }}
      </h1>
    </div>

    <!-- General Settings Card -->
    <UCard>
      <template #header>
        <h3 class="font-bold text-highlighted">
          {{ $t('profile.general') }}
        </h3>
        <p class="text-xs text-muted">
          {{ $t('profile.generalDesc') }}
        </p>
      </template>

      <div class="space-y-4">
        <div class="flex items-center gap-4">
          <UAvatar
            :src="avatarPreview || avatarUrl || undefined"
            :text="initials"
            :alt="displayName || user?.email || ''"
            size="3xl"
            :ui="{ root: 'border border-default' }"
          />
          <div class="space-y-1.5">
            <UButton
              :label="$t('profile.changePhoto')"
              icon="i-lucide-upload"
              variant="outline"
              color="neutral"
              size="sm"
              @click="fileInput?.click()"
            />
            <p class="text-xs text-muted">
              {{ $t('profile.photoHint') }}
            </p>
          </div>
          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            class="hidden"
            @change="onAvatarChange"
          >
        </div>

        <UFormField
          :label="$t('profile.displayName')"
          name="displayName"
        >
          <UInput
            v-model="displayName"
            :placeholder="$t('profile.displayNamePlaceholder')"
            class="w-full"
          />
        </UFormField>

        <UFormField
          :label="$t('profile.languagePreference')"
          name="language"
        >
          <LanguageSelect />
        </UFormField>

        <UButton
          :loading="profileLoading"
          @click="onProfileSave"
        >
          {{ $t('profile.saveChanges') }}
        </UButton>
      </div>
    </UCard>

    <!-- Email change Card -->
    <UCard>
      <template #header>
        <h3 class="font-bold text-highlighted">
          {{ $t('profile.emailAddress') }}
        </h3>
        <p class="text-xs text-muted">
          {{ $t('profile.emailDesc') }}
        </p>
      </template>

      <UForm
        :schema="emailSchema"
        :state="emailState"
        class="space-y-4"
        @submit="onEmailSubmit"
      >
        <UFormField
          :label="$t('profile.currentEmail')"
          name="currentEmail"
        >
          <UInput
            :value="user?.email"
            disabled
            class="w-full"
          />
        </UFormField>

        <UFormField
          :label="$t('profile.newEmail')"
          name="email"
        >
          <UInput
            v-model="emailState.email"
            type="email"
            :placeholder="$t('profile.newEmailPlaceholder')"
            class="w-full"
          />
        </UFormField>

        <UButton
          type="submit"
          :loading="emailLoading"
        >
          {{ $t('profile.updateEmail') }}
        </UButton>
      </UForm>
    </UCard>

    <!-- Password update Card -->
    <UCard>
      <template #header>
        <h3 class="font-bold text-highlighted">
          {{ $t('profile.security') }}
        </h3>
        <p class="text-xs text-muted">
          {{ $t('profile.securityDesc') }}
        </p>
      </template>

      <UForm
        :schema="passwordSchema"
        :state="passwordState"
        class="space-y-4"
        @submit="onPasswordSubmit"
      >
        <UFormField
          :label="$t('profile.currentPassword')"
          name="currentPassword"
        >
          <UInput
            v-model="passwordState.currentPassword"
            type="password"
            :placeholder="$t('profile.currentPasswordPlaceholder')"
            class="w-full"
          />
        </UFormField>

        <UFormField
          :label="$t('profile.newPassword')"
          name="newPassword"
        >
          <UInput
            v-model="passwordState.newPassword"
            type="password"
            :placeholder="$t('profile.newPasswordPlaceholder')"
            class="w-full"
          />
        </UFormField>

        <UFormField
          :label="$t('profile.confirmPassword')"
          name="confirmPassword"
        >
          <UInput
            v-model="passwordState.confirmPassword"
            type="password"
            :placeholder="$t('profile.confirmPasswordPlaceholder')"
            class="w-full"
          />
        </UFormField>

        <UButton
          type="submit"
          :loading="passwordLoading"
        >
          {{ $t('profile.updatePassword') }}
        </UButton>
      </UForm>
    </UCard>

    <!-- Danger zone Card -->
    <UCard class="border-red-500/20">
      <template #header>
        <h3 class="font-bold text-red-500">
          {{ $t('profile.dangerZone') }}
        </h3>
      </template>

      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div class="space-y-1">
          <h4 class="text-sm font-semibold text-highlighted">
            {{ $t('profile.deleteAccount') }}
          </h4>
          <p class="text-xs text-muted max-w-md">
            {{ $t('profile.deleteAccountDesc') }}
          </p>
        </div>
        <UButton
          color="error"
          variant="solid"
          class="w-fit"
          @click="() => { deleteModalOpen = true }"
        >
          {{ $t('profile.deleteAccount') }}
        </UButton>
      </div>
    </UCard>

    <!-- Account Delete Confirmation Modal -->
    <UModal v-model:open="deleteModalOpen">
      <template #title>
        <div class="flex items-center justify-center gap-3">
          <UIcon
            name="i-lucide-alert-triangle"
            class="size-6 text-red-500"
          />
          <span class="font-semibold text-highlighted text-xl">{{ $t('profile.deleteConfirmTitle') }}</span>
        </div>
      </template>
      <template #body>
        <p class="text-sm text-muted">
          {{ $t('profile.deleteConfirmDesc') }}
        </p>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            :label="$t('profile.cancel')"
            variant="outline"
            color="neutral"
            @click="() => { deleteModalOpen = false }"
          />
          <UButton
            :label="$t('profile.deleteAccount')"
            color="error"
            :loading="deleteLoading"
            @click="handleDeleteAccount"
          />
        </div>
      </template>
    </UModal>
  </div>
</template>
