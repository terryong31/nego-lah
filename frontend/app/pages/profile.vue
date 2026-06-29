<script setup lang="ts">
import * as z from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

definePageMeta({
  middleware: 'auth'
})

const { call } = useApi()
const user = useSupabaseUser()
const supabase = useSupabaseClient()
const router = useRouter()
const toast = useToast()

// General Settings - display name & profile picture (stored in user metadata)
const displayName = ref(user.value?.user_metadata?.display_name || '')
const avatarUrl = ref(user.value?.user_metadata?.avatar_url || '')
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
  avatarUrl.value = u?.user_metadata?.avatar_url || ''
})

function onAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    toast.add({ title: 'Image too large', description: 'Please choose an image under 2MB.', color: 'error' })
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
    toast.add({ title: 'Profile updated', description: 'Your profile settings have been saved.', color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Failed to update profile', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    profileLoading.value = false
  }
}

// Change Email
const emailSchema = z.object({
  email: z.string().email('Invalid email address')
})
type EmailSchema = z.output<typeof emailSchema>
const emailLoading = ref(false)

async function onEmailSubmit(payload: FormSubmitEvent<EmailSchema>) {
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
    toast.add({ title: 'Email change requested', description: 'Please check your inbox for verification links.', color: 'success' })
  } catch (err) {
    toast.add({ title: 'Failed to update email', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
  } finally {
    emailLoading.value = false
  }
}

// Change Password
const passwordSchema = z.object({
  currentPassword: z.string().min(8, 'Must be at least 8 characters'),
  newPassword: z.string().min(8, 'Must be at least 8 characters'),
  confirmPassword: z.string().min(8, 'Must be at least 8 characters')
}).refine(data => data.newPassword === data.confirmPassword, {
  message: 'Passwords don\'t match',
  path: ['confirmPassword']
})
type PasswordSchema = z.output<typeof passwordSchema>
const passwordLoading = ref(false)

async function onPasswordSubmit(payload: FormSubmitEvent<PasswordSchema>) {
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
    toast.add({ title: 'Password updated', description: 'Your password was changed successfully.', color: 'success' })
  } catch (err) {
    toast.add({ title: 'Failed to update password', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
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
    toast.add({ title: 'Account deleted', description: 'Your account and data have been permanently removed.', color: 'success' })
    router.push('/')
  } catch (err) {
    toast.add({ title: 'Failed to delete account', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
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
        Profile Settings
      </h1>
    </div>

    <!-- General Settings Card -->
    <UCard>
      <template #header>
        <h3 class="font-bold text-highlighted">
          General
        </h3>
        <p class="text-xs text-muted">
          Update your display name and profile picture.
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
              label="Change photo"
              icon="i-lucide-upload"
              variant="outline"
              color="neutral"
              size="sm"
              @click="fileInput?.click()"
            />
            <p class="text-xs text-muted">
              JPG, PNG or GIF. Max 2MB.
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
          label="Display Name"
          name="displayName"
        >
          <UInput
            v-model="displayName"
            placeholder="Enter your display name"
            class="w-full"
          />
        </UFormField>

        <UButton
          :loading="profileLoading"
          @click="onProfileSave"
        >
          Save Changes
        </UButton>
      </div>
    </UCard>

    <!-- Email change Card -->
    <UCard>
      <template #header>
        <h3 class="font-bold text-highlighted">
          Email Address
        </h3>
        <p class="text-xs text-muted">
          Update the email associated with your account.
        </p>
      </template>

      <UForm
        :schema="emailSchema"
        class="space-y-4"
        @submit="onEmailSubmit"
      >
        <UFormField
          label="Current Email"
          name="currentEmail"
        >
          <UInput
            :value="user?.email"
            disabled
            class="w-full"
          />
        </UFormField>

        <UFormField
          label="New Email Address"
          name="email"
        >
          <UInput
            type="email"
            placeholder="Enter new email"
            class="w-full"
          />
        </UFormField>

        <UButton
          type="submit"
          :loading="emailLoading"
        >
          Update Email
        </UButton>
      </UForm>
    </UCard>

    <!-- Password update Card -->
    <UCard>
      <template #header>
        <h3 class="font-bold text-highlighted">
          Security Settings
        </h3>
        <p class="text-xs text-muted">
          Change your current login credentials.
        </p>
      </template>

      <UForm
        :schema="passwordSchema"
        class="space-y-4"
        @submit="onPasswordSubmit"
      >
        <UFormField
          label="Current Password"
          name="currentPassword"
        >
          <UInput
            type="password"
            placeholder="Enter current password"
            class="w-full"
          />
        </UFormField>

        <UFormField
          label="New Password"
          name="newPassword"
        >
          <UInput
            type="password"
            placeholder="Create new password"
            class="w-full"
          />
        </UFormField>

        <UFormField
          label="Confirm New Password"
          name="confirmPassword"
        >
          <UInput
            type="password"
            placeholder="Confirm new password"
            class="w-full"
          />
        </UFormField>

        <UButton
          type="submit"
          :loading="passwordLoading"
        >
          Update Password
        </UButton>
      </UForm>
    </UCard>

    <!-- Danger zone Card -->
    <UCard class="border-red-500/20">
      <template #header>
        <h3 class="font-bold text-red-500">
          Danger Zone
        </h3>
      </template>

      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div class="space-y-1">
          <h4 class="text-sm font-semibold text-highlighted">
            Delete Account
          </h4>
          <p class="text-xs text-muted max-w-md">
            This action cannot be undone. All active chat settings and rooms will be erased. Past orders and receipts are kept for business records.
          </p>
        </div>
        <UButton
          color="error"
          variant="outline"
          class="w-fit"
          @click="deleteModalOpen = true"
        >
          Delete Account
        </UButton>
      </div>
    </UCard>

    <!-- Account Delete Confirmation Modal -->
    <UModal v-model:open="deleteModalOpen">
      <template #content>
        <div class="p-6 space-y-4">
          <div class="flex items-start gap-4">
            <div class="p-2 bg-red-100 dark:bg-red-950 text-red-500 rounded-full shrink-0">
              <UIcon
                name="i-lucide-alert-triangle"
                class="size-6"
              />
            </div>
            <div>
              <h3 class="text-lg font-bold text-highlighted">
                Are you absolutely sure?
              </h3>
              <p class="text-sm text-muted mt-1">
                This action is permanent and cannot be undone. You will lose access to all bargain history rooms instantly.
              </p>
            </div>
          </div>
          <div class="flex justify-end gap-3 pt-4">
            <UButton
              label="Cancel"
              variant="outline"
              color="neutral"
              @click="deleteModalOpen = false"
            />
            <UButton
              label="Delete Account"
              color="error"
              :loading="deleteLoading"
              @click="handleDeleteAccount"
            />
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
