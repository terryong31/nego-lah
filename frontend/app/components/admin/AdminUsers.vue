<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'

const { call } = useAdminApi()
const toast = useToast()

interface AdminUser {
  id: string
  email: string
  display_name: string
  avatar_url?: string
  is_banned: boolean
  ai_enabled: boolean
  admin_intervening: boolean
  created_at: string
}

const { data: users, pending, refresh } = useAsyncData<AdminUser[]>(
  'admin-users',
  () => call<AdminUser[]>('/users'),
  { default: () => [] }
)

const busy = ref<string | null>(null)

async function toggleBan(u: AdminUser) {
  busy.value = u.id
  try {
    await call(`/users/${u.id}/ban`, { method: 'PUT', body: { is_banned: !u.is_banned } })
    u.is_banned = !u.is_banned
    toast.add({ title: u.is_banned ? 'User banned' : 'User unbanned', color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Action failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

async function toggleAi(u: AdminUser) {
  const originalState = u.ai_enabled
  u.ai_enabled = !u.ai_enabled

  try {
    await call(`/users/${u.id}/ai`, { method: 'PUT', body: { ai_enabled: u.ai_enabled } })
    toast.add({ title: u.ai_enabled ? 'AI enabled' : 'AI disabled', color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    u.ai_enabled = originalState
    toast.add({ title: 'Action failed', description: e.data?.detail || e.message, color: 'error' })
  }
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }) : '-'
}

// ---- Edit profile modal ----
const editOpen = ref(false)
const saving = ref(false)
const editing = ref<AdminUser | null>(null)
const form = reactive({ display_name: '', avatar_url: '' })

function openEdit(u: AdminUser) {
  editing.value = u
  form.display_name = u.display_name || ''
  form.avatar_url = u.avatar_url || ''
  editOpen.value = true
}

async function saveProfile() {
  if (!editing.value) return
  saving.value = true
  try {
    await call(`/users/${editing.value.id}/profile`, {
      method: 'PUT',
      body: { display_name: form.display_name, avatar_url: form.avatar_url || null }
    })
    editing.value.display_name = form.display_name
    editing.value.avatar_url = form.avatar_url || undefined
    toast.add({ title: 'Profile updated', color: 'success' })
    editOpen.value = false
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Update failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    saving.value = false
  }
}

// ---- Delete ----
async function remove(u: AdminUser) {
  if (!confirm(`Delete ${u.display_name || u.email}? This permanently removes their account and chats.`)) return
  busy.value = u.id
  try {
    await call(`/users/${u.id}`, { method: 'DELETE' })
    toast.add({ title: 'User deleted', color: 'success' })
    await refresh()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Delete failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

const columns: TableColumn<AdminUser>[] = [
  { accessorKey: 'display_name', header: 'User' },
  { accessorKey: 'is_banned', header: 'Status' },
  { accessorKey: 'ai_enabled', header: 'AI' },
  { accessorKey: 'created_at', header: 'Joined' },
  { id: 'actions', header: '' }
]
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted">
        {{ users.length }} user(s)
      </p>
      <UButton
        size="xs"
        variant="ghost"
        icon="i-lucide-refresh-cw"
        label="Refresh"
        :loading="pending"
        @click="refresh()"
      />
    </div>

    <UTable
      :columns="columns"
      :data="users"
      :loading="pending"
      :ui="{ td: 'py-2' }"
    >
      <template #display_name-cell="{ row }">
        <div class="flex items-center gap-3">
          <UAvatar
            :src="row.original.avatar_url"
            :alt="row.original.email"
            size="md"
          />
          <div class="min-w-0">
            <p class="font-medium text-highlighted truncate">
              {{ row.original.display_name }}
            </p>
            <p class="text-xs text-muted truncate">
              {{ row.original.email }}
            </p>
          </div>
        </div>
      </template>

      <template #is_banned-cell="{ row }">
        <UBadge
          v-if="row.original.is_banned"
          color="error"
          variant="subtle"
          size="sm"
        >
          Banned
        </UBadge>
        <UBadge
          v-else
          color="success"
          variant="subtle"
          size="sm"
        >
          Active
        </UBadge>
      </template>

      <template #ai_enabled-cell="{ row }">
        <USwitch
          :model-value="row.original.ai_enabled"
          @update:model-value="toggleAi(row.original)"
        />
      </template>

      <template #created_at-cell="{ row }">
        <span class="text-sm text-muted">{{ formatDate(row.original.created_at) }}</span>
      </template>

      <template #actions-cell="{ row }">
        <div class="flex items-center justify-end gap-1">
          <UButton
            size="xs"
            color="neutral"
            variant="ghost"
            icon="i-lucide-pencil"
            :disabled="busy === row.original.id"
            @click="openEdit(row.original)"
          />
          <UButton
            size="xs"
            :color="row.original.is_banned ? 'neutral' : 'error'"
            :variant="row.original.is_banned ? 'outline' : 'soft'"
            :label="row.original.is_banned ? 'Unban' : 'Ban'"
            :loading="busy === row.original.id"
            @click="toggleBan(row.original)"
          />
          <UButton
            size="xs"
            color="error"
            variant="ghost"
            icon="i-lucide-trash-2"
            :loading="busy === row.original.id"
            @click="remove(row.original)"
          />
        </div>
      </template>
    </UTable>

    <!-- Edit profile modal -->
    <UModal
      v-model:open="editOpen"
      title="Edit user"
      :description="editing?.email"
      :ui="{ content: 'max-w-md' }"
    >
      <template #body>
        <div class="space-y-4">
          <div class="flex justify-center">
            <UAvatar
              :src="form.avatar_url || undefined"
              :alt="form.display_name || editing?.email"
              size="3xl"
            />
          </div>
          <UFormField label="Display name">
            <UInput
              v-model="form.display_name"
              placeholder="Display name"
              class="w-full"
            />
          </UFormField>
          <UFormField
            label="Avatar URL"
            hint="Direct image link"
          >
            <UInput
              v-model="form.avatar_url"
              placeholder="https://…"
              class="w-full"
            />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            label="Cancel"
            :disabled="saving"
            @click="editOpen = false"
          />
          <UButton
            label="Save changes"
            :loading="saving"
            @click="saveProfile"
          />
        </div>
      </template>
    </UModal>
  </div>
</template>
