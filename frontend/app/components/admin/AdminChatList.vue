<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'
import type { ChatSummary } from '~/utils/adminChat'

/**
 * The console's conversation list — one component for both layouts.
 *
 * Desktop and mobile used to carry a byte-identical copy of this markup, so
 * every fix had to be made twice and the two copies had already started to
 * drift. The only real difference was the wrapper around them, which is what
 * `AdminChats.vue` still owns.
 */

const props = defineProps<{
  /** Already filtered and sorted by the parent. */
  chats: ChatSummary[]
  /** How many the server actually sent — tells "nothing yet" from "no match". */
  total: number
  pending: boolean
  selected: string | null
  markingRead: string | null
  archiving: string | null
  sortItems: { label: string, value: string }[]
}>()

const emit = defineEmits<{
  refresh: []
  open: [userId: string]
  markRead: [userId: string, read: boolean]
  archive: [userId: string, archived: boolean]
  info: [chat: ChatSummary]
}>()

const search = defineModel<string>('search', { required: true })
const sortKey = defineModel<string>('sortKey', { required: true })
const showArchived = defineModel<boolean>('showArchived', { required: true })

const { t } = useI18n()

// The sort spent 160px of a 377px pane spelling out a choice that is almost
// always the default. As a funnel it costs an icon, and tints when the operator
// has moved off "Recent activity" so a non-default order is never silent.
const activeSortLabel = computed(
  () => props.sortItems.find(i => i.value === sortKey.value)?.label ?? ''
)

const sortMenu = computed<DropdownMenuItem[]>(() =>
  props.sortItems.map(item => ({
    label: item.label,
    type: 'checkbox' as const,
    checked: sortKey.value === item.value,
    // Re-picking the active sort must not clear it — there is no "unsorted".
    onUpdateChecked: (checked: boolean) => {
      if (checked) sortKey.value = item.value
    },
    onSelect: (e: Event) => e.preventDefault()
  }))
)

/**
 * SPEC-063 — a row needs more than one verb. The mail icon it replaces did
 * exactly one thing and read as "send mail", which is not what it did.
 */
function rowActions(chat: ChatSummary): DropdownMenuItem[][] {
  return [
    [
      {
        label: chat.unread ? t('admin.chatsSection.markRead') : t('admin.chatsSection.markUnread'),
        icon: chat.unread ? 'i-lucide-mail-open' : 'i-lucide-mail',
        onSelect: () => emit('markRead', chat.user_id, chat.unread)
      },
      {
        label: chat.archived ? t('admin.chatsSection.unarchive') : t('admin.chatsSection.archive'),
        icon: chat.archived ? 'i-lucide-archive-restore' : 'i-lucide-archive',
        onSelect: () => emit('archive', chat.user_id, !chat.archived)
      }
    ],
    [
      {
        label: t('admin.chatsSection.userInfo'),
        icon: 'i-lucide-circle-user-round',
        onSelect: () => emit('info', chat)
      }
    ]
  ]
}

// Three empty states, not one: an operator who searched, an operator looking at
// an empty archive, and a store nobody has messaged yet are owed different
// sentences.
const emptyState = computed(() => {
  if (props.total > 0) {
    return {
      title: t('admin.chatsSection.noMatchTitle'),
      description: t('admin.chatsSection.noMatch'),
      icon: 'i-lucide-search-x'
    }
  }
  if (showArchived.value) {
    return {
      title: t('admin.chatsSection.emptyArchivedTitle'),
      description: t('admin.chatsSection.emptyArchived'),
      icon: 'i-lucide-archive'
    }
  }
  return {
    title: t('admin.chatsSection.emptyListTitle'),
    description: t('admin.chatsSection.emptyList'),
    icon: 'i-lucide-messages-square'
  }
})
</script>

<template>
  <aside class="w-full h-full flex flex-col min-h-0 overflow-hidden">
    <!-- One control strip. The All / Unread / Read segmented control that used
         to sit above it duplicated both the "Unread first" sort and the row's
         own chip, in the pane with the least room to spare (SPEC-062). -->
    <div class="h-14 px-3 flex items-center gap-2 border-b border-default shrink-0">
      <UInput
        v-model="search"
        data-testid="chats-search"
        size="md"
        icon="i-lucide-search"
        class="flex-1 min-w-0"
        :placeholder="$t('admin.chatsSection.searchPlaceholder')"
        :aria-label="$t('admin.chatsSection.searchPlaceholder')"
      />
      <UDropdownMenu
        :items="sortMenu"
        :content="{ align: 'end' }"
      >
        <UButton
          data-testid="chats-sort"
          size="md"
          variant="ghost"
          :color="sortKey === 'recent' ? 'neutral' : 'primary'"
          icon="i-lucide-funnel"
          :aria-label="$t('admin.chatsSection.sortLabel')"
          :title="`${$t('admin.chatsSection.sortLabel')}: ${activeSortLabel}`"
        />
      </UDropdownMenu>
      <UButton
        data-testid="chats-archived-toggle"
        size="md"
        variant="ghost"
        :color="showArchived ? 'primary' : 'neutral'"
        icon="i-lucide-archive"
        :aria-label="$t('admin.chatsSection.showArchived')"
        :aria-pressed="showArchived"
        :title="$t('admin.chatsSection.showArchived')"
        @click="showArchived = !showArchived"
      />
      <UButton
        data-testid="chats-refresh"
        size="md"
        variant="ghost"
        color="neutral"
        icon="i-lucide-refresh-cw"
        :loading="pending"
        :aria-label="$t('admin.chatsSection.refresh')"
        :title="$t('admin.chatsSection.refresh')"
        @click="emit('refresh')"
      />
    </div>

    <div class="flex-1 overflow-y-auto">
      <div
        v-if="pending"
        class="p-3 space-y-2"
      >
        <USkeleton
          v-for="i in 6"
          :key="i"
          class="h-14 w-full"
        />
      </div>
      <UEmpty
        v-else-if="chats.length === 0"
        :icon="emptyState.icon"
        :title="emptyState.title"
        :description="emptyState.description"
        variant="naked"
        size="sm"
        class="p-6 text-center"
      />
      <div
        v-for="c in chats"
        v-else
        :key="c.user_id"
        class="relative border-b border-default"
        :class="selected === c.user_id ? 'bg-elevated' : ''"
      >
        <button
          class="w-full text-left px-3 py-3 pr-16 hover:bg-elevated/50 transition-colors"
          @click="emit('open', c.user_id)"
        >
          <div class="flex items-center gap-2 mb-1">
            <UAvatar
              :src="c.avatar_url || undefined"
              :alt="c.display_name"
              size="2xs"
              icon="i-lucide-user"
            />
            <span class="text-sm font-medium text-highlighted truncate">{{ c.display_name }}</span>
            <UBadge
              v-if="c.ai_enabled === false"
              color="warning"
              variant="subtle"
              size="xs"
              label="HITL"
              class="ml-1"
            />
          </div>
          <p class="text-sm text-default truncate">
            {{ c.last_message || '—' }}
          </p>
          <p class="text-xs text-dimmed">
            {{ c.message_count }} messages
          </p>
        </button>

        <!-- SPEC-053: the row's controls sit OUTSIDE the row button (nesting one
             button in another is invalid markup) so a thread can be triaged
             without being opened. The chip stays a chip: it is state, and only
             the menu beside it is an action. -->
        <div class="absolute top-2.5 right-2 flex items-center gap-1.5">
          <UChip v-if="c.unread" />
          <UDropdownMenu
            :items="rowActions(c)"
            :content="{ align: 'end' }"
          >
            <UButton
              :data-testid="`chat-actions-${c.user_id}`"
              size="xs"
              variant="ghost"
              color="neutral"
              icon="i-lucide-ellipsis-vertical"
              :loading="markingRead === c.user_id || archiving === c.user_id"
              :aria-label="$t('admin.chatsSection.rowActions')"
              :title="$t('admin.chatsSection.rowActions')"
            />
          </UDropdownMenu>
        </div>
      </div>
    </div>
  </aside>
</template>
