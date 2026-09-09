<script setup lang="ts">
import type { SplitterItem } from '@nuxt/ui'

const { t } = useI18n()
const { call } = useAdminApi()
const toast = useToast()

const splitterItems: SplitterItem[] = [
  { slot: 'list', minSize: 18, defaultSize: 20, maxSize: 45, class: 'flex flex-col min-h-0' },
  { slot: 'thread', minSize: 40, defaultSize: 80, class: 'flex flex-col min-h-0' }
]

// Live typing presence — mirrors the customer chat page. The admin client isn't
// a Supabase-authenticated session (the console uses its own cookie auth), but
// the broadcast channel is public so the anon client can still send/receive.
const { remoteTyping: customerTyping, join: joinTyping, ping: pingTyping } = useTypingChannel()

interface ChatSummary {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  last_message: string
  last_role: string
  unread: boolean
  ai_enabled?: boolean
  admin_intervening?: boolean
  last_activity?: string | null
  admin_last_read_at?: string | null
}
interface ChatMessage {
  role: string
  content: string
  source?: string
}

const { data: chats, pending, refresh } = useAsyncData<ChatSummary[]>(
  'admin-chats',
  () => call<ChatSummary[]>('/chats'),
  { default: () => [] }
)

const selected = ref<string | null>(null)
const selectedChat = computed(() => chats.value.find(c => c.user_id === selected.value))

// Read/unread filter for the conversation list.
type ChatFilter = 'all' | 'unread' | 'read'
const filter = ref<ChatFilter>('all')
const filterItems = computed(() => [
  { label: t('admin.chatsSection.filterAll'), value: 'all' as const },
  { label: t('admin.filterUnread'), value: 'unread' as const },
  { label: t('admin.filterRead'), value: 'read' as const }
])
const filteredChats = computed(() =>
  chats.value.filter((c) => {
    if (filter.value === 'unread') return c.unread
    if (filter.value === 'read') return !c.unread
    return true
  })
)

// Free-text search over the conversation list — name + last message, client-side.
const search = ref('')

// Sort order for the list. 'recent' (default) reads last_activity; the backend
// sends it (SPEC-046 #42), and falls back to message_count when it's absent.
type ChatSort = 'recent' | 'unread' | 'messages'
const sortKey = ref<ChatSort>('recent')
const sortItems = computed(() => [
  { label: t('admin.chatsSection.sortRecent'), value: 'recent' as const },
  { label: t('admin.chatsSection.sortUnread'), value: 'unread' as const },
  { label: t('admin.chatsSection.sortMessages'), value: 'messages' as const }
])

function activityTime(c: ChatSummary): number {
  const ms = c.last_activity ? Date.parse(c.last_activity) : NaN
  return Number.isNaN(ms) ? c.message_count : ms
}

const visibleChats = computed(() => {
  const q = search.value.trim().toLowerCase()
  const rows = filteredChats.value.filter((c) => {
    if (!q) return true
    return c.display_name.toLowerCase().includes(q)
      || (c.last_message || '').toLowerCase().includes(q)
  })
  return [...rows].sort((a, b) => {
    if (sortKey.value === 'messages') return b.message_count - a.message_count
    if (sortKey.value === 'unread') {
      if (a.unread !== b.unread) return a.unread ? -1 : 1
      return activityTime(b) - activityTime(a)
    }
    return activityTime(b) - activityTime(a)
  })
})

// SPEC-053 — read state is a real watermark on the server now, so the dot is
// something we can actually clear. Optimistic: the operator sees the row settle
// on click, and a failed write puts the dot back rather than lying about it.
const markingRead = ref<string | null>(null)

async function markRead(userId: string, read: boolean) {
  const chat = chats.value.find(c => c.user_id === userId)
  if (!chat || chat.unread === !read) return

  const previous = chat.unread
  chat.unread = !read
  markingRead.value = userId
  try {
    const res = await call<{ unread: boolean, admin_last_read_at: string | null }>(
      `/chats/${userId}/read`,
      { method: 'POST', body: { read } }
    )
    chat.unread = res?.unread ?? !read
    chat.admin_last_read_at = res?.admin_last_read_at ?? null
  } catch (err) {
    chat.unread = previous
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('admin.chatsSection.markFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    markingRead.value = null
  }
}

const messages = ref<ChatMessage[]>([])
const loadingMsgs = ref(false)
const reply = ref('')
const sending = ref(false)
const scroller = ref<HTMLElement | null>(null)

// Human-in-the-loop (HITL) AI status and takeover
const currentAiEnabled = ref(true)
const togglingAi = ref(false)

watch(selectedChat, (chat) => {
  if (chat && typeof chat.ai_enabled === 'boolean') {
    currentAiEnabled.value = chat.ai_enabled
  } else {
    currentAiEnabled.value = true
  }
}, { immediate: true })

// Pull the authoritative AI status for a conversation from the backend. Called
// whenever a system notice lands on the realtime channel (SPEC-046 #39) — the
// agent's `transfer_to_human` and the rate-limit handoff both flip
// `chat_settings.ai_enabled` server-side without any signal the console can
// pattern-match, so we just ask.
async function syncAiStatus(userId: string) {
  try {
    const res = await call<{ ai_enabled: boolean }>(`/users/${userId}/ai`)
    if (userId === selected.value && typeof res?.ai_enabled === 'boolean') {
      currentAiEnabled.value = res.ai_enabled
    }
  } catch {
    // Best-effort — the next list refresh will reconcile it anyway.
  }
}

async function toggleAi() {
  if (!selected.value || togglingAi.value) return
  togglingAi.value = true
  const target = !currentAiEnabled.value
  try {
    await call(`/users/${selected.value}/ai`, { method: 'PUT', body: { ai_enabled: target } })
    currentAiEnabled.value = target
    if (selectedChat.value) {
      selectedChat.value.ai_enabled = target
    }
    toast.add({
      title: target ? 'AI Assistant Resumed' : 'Human Specialist Active',
      description: target ? 'AI will now answer customer queries.' : 'AI is paused. You have taken over the conversation.',
      color: target ? 'success' : 'warning'
    })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'AI toggle failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    togglingAi.value = false
  }
}

// Mobile responsive layout detection (< 768px)
const isMobile = ref(false)

function updateMobile() {
  if (typeof window !== 'undefined') {
    isMobile.value = window.innerWidth > 0 && window.innerWidth < 768
  }
}

onMounted(() => {
  updateMobile()
  window.addEventListener('resize', updateMobile)
})

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateMobile)
  }
})

function scrollToBottom() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}

watch(reply, (val) => {
  if (val.trim()) pingTyping()
})

async function open(userId: string) {
  selected.value = userId
  loadingMsgs.value = true
  // Reading it IS reading it. Fire and forget — a failed stamp must not block
  // the thread from loading.
  markRead(userId, true)
  joinTyping(userId, {
    listenFor: 'customer',
    sendAs: 'seller',
    onMessage: (payload) => {
      const msg = payload as { content?: string, role?: string, source?: string }
      if (!msg || !msg.content) return

      // The backend broadcasts admin messages to the same chat channel this
      // console listens on, so our own send arrives back here — and `send()`
      // has already appended it optimistically. (Mirror of the customer chat,
      // which drops the `human` echo for the same reason.)
      if (msg.source === 'admin') return

      messages.value.push({
        role: msg.role === 'system' ? 'system' : (msg.role ?? 'ai'),
        content: msg.content,
        source: msg.source
      })
      // A system notice means the AI/human handover state may have just
      // changed — an agent `transfer_to_human`, a rate-limit handoff, or the
      // manual toggle. Re-sync from the authoritative flag rather than
      // pattern-matching the notice text (which only ever matched the manual
      // toggle's wording and left the badge stale on auto-handoffs).
      if (msg.role === 'system') {
        syncAiStatus(userId)
        refresh()
      }
      scrollToBottom()
    }
  })
  try {
    const res = await call<{ user_id: string, messages: ChatMessage[] }>(`/chats/${userId}?limit=100`)
    messages.value = res.messages || []
    scrollToBottom()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Failed to load chat', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    loadingMsgs.value = false
  }
}

async function send() {
  const text = reply.value.trim()
  if (!text || !selected.value) return
  sending.value = true
  try {
    await call(`/chats/${selected.value}/message`, { method: 'POST', body: { message: text } })
    messages.value.push({ role: 'ai', content: text, source: 'admin' })
    reply.value = ''
    scrollToBottom()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: 'Send failed', description: e.data?.detail || e.message, color: 'error' })
  } finally {
    sending.value = false
  }
}

// Map our stored messages to the shape UChatMessage expects.
// Seller side (AI / admin) sits on the right; the buyer on the left. A
// per-message avatar override (spread after the shared assistant/user props in
// UChatMessages) lets us distinguish the AI bot from the human seller.
const rendered = computed(() => {
  return messages.value
    .map((m, i) => {
      const isAdmin = m.source === 'admin'
      const seller = m.role === 'ai' || isAdmin
      const role = m.role === 'system' ? 'system' : (seller ? 'assistant' : 'user')
      return {
        id: String(i),
        role: role as 'system' | 'assistant' | 'user',
        side: seller ? 'right' : 'left',
        admin: isAdmin,
        parts: [{ type: 'text' as const, text: m.content }]
      }
    })
})

interface RenderedMessage {
  role?: string
  admin?: boolean
  parts?: { type: string, text?: string }[]
}

function getMessageText(message: RenderedMessage) {
  if (!message?.parts) return ''
  return message.parts
    .filter(p => p.type === 'text')
    .map(p => p.text)
    .join('')
}

function systemLabel(message: RenderedMessage) {
  return getMessageText(message).replace(/^[\s-]+|[\s-]+$/g, '')
}

// SPEC-027: the AI's newlines are message boundaries, a human's are line
// breaks. `admin` marks a message the seller typed here, so their Shift+Enter
// stays in one bubble — exactly what the buyer sees on their side.
function blocksFor(message: RenderedMessage) {
  return messageBlocks(getMessageText(message), shouldSplit(message.role, message.admin ? 'admin' : 'ai'))
}

// Item 29: Disable checkout CTA card after payment has completed
const isPaidDeal = computed(() => {
  return messages.value.some((m) => {
    const text = (m.content || '').toLowerCase()
    return text.includes('payment received') || text.includes('deal closed') || text.includes('order completed')
  })
})
</script>

<template>
  <div class="flex-1 min-h-0 w-full flex overflow-hidden">
    <!-- Desktop view (>= md: 768px): Dual-pane USplitter -->
    <USplitter
      v-if="!isMobile"
      id="admin-chats-splitter"
      :items="splitterItems"
      class="flex-1 min-h-0 w-full"
      :ui="{
        handle: 'w-0.5 bg-border hover:bg-primary data-[state=drag]:bg-primary transition-colors cursor-col-resize'
      }"
    >
      <!-- Conversation list -->
      <template #list>
        <aside class="w-full h-full flex flex-col min-h-0 overflow-hidden">
          <div class="h-12 px-3 flex items-center gap-2 border-b border-default shrink-0">
            <div class="flex-1 flex gap-0.5 p-0.5 rounded-md bg-elevated/50">
              <UButton
                v-for="f in filterItems"
                :key="f.value"
                size="xs"
                :color="filter === f.value ? 'primary' : 'neutral'"
                :variant="filter === f.value ? 'solid' : 'ghost'"
                class="flex-1 justify-center"
                :label="f.label"
                @click="filter = f.value"
              />
            </div>
            <UButton
              size="xs"
              variant="ghost"
              icon="i-lucide-refresh-cw"
              :loading="pending"
              @click="refresh()"
            />
          </div>

          <div class="px-3 py-2 flex items-center gap-2 border-b border-default shrink-0">
            <UInput
              v-model="search"
              size="xs"
              icon="i-lucide-search"
              class="flex-1"
              :placeholder="$t('admin.chatsSection.searchPlaceholder')"
              :aria-label="$t('admin.chatsSection.searchPlaceholder')"
            />
            <USelect
              v-model="sortKey"
              size="xs"
              :items="sortItems"
              class="w-32 shrink-0"
              :aria-label="$t('admin.chatsSection.sortLabel')"
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
              v-else-if="visibleChats.length === 0"
              :description="chats.length === 0 ? $t('admin.chatsSection.emptyList') : $t('admin.chatsSection.noMatch')"
              variant="naked"
              size="sm"
              class="p-6 text-center"
            />
            <div
              v-for="c in visibleChats"
              v-else
              :key="c.user_id"
              class="relative border-b border-default"
              :class="selected === c.user_id ? 'bg-elevated' : ''"
            >
              <button
                class="w-full text-left px-3 py-3 pr-16 hover:bg-elevated/50 transition-colors"
                @click="open(c.user_id)"
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

              <!-- SPEC-053: the read toggle sits OUTSIDE the row button (nesting one
                   button in another is invalid markup) so a thread can be dismissed
                   without being opened. -->
              <div class="absolute top-2.5 right-2 flex items-center gap-1.5">
                <UChip v-if="c.unread" />
                <UButton
                  :data-testid="`chat-read-toggle-${c.user_id}`"
                  size="xs"
                  variant="ghost"
                  color="neutral"
                  :icon="c.unread ? 'i-lucide-mail-open' : 'i-lucide-mail'"
                  :loading="markingRead === c.user_id"
                  :aria-label="c.unread ? $t('admin.chatsSection.markRead') : $t('admin.chatsSection.markUnread')"
                  :title="c.unread ? $t('admin.chatsSection.markRead') : $t('admin.chatsSection.markUnread')"
                  @click="markRead(c.user_id, c.unread)"
                />
              </div>
            </div>
          </div>
        </aside>
      </template>

      <!-- Conversation thread -->
      <template #thread>
        <section class="w-full h-full min-w-0 flex flex-col min-h-0 overflow-hidden">
          <UEmpty
            v-if="!selected"
            icon="i-lucide-messages-square"
            :description="$t('admin.chatsSection.emptyDesc')"
            variant="naked"
            class="flex-1 justify-center"
          />

          <template v-else>
            <!-- Thread header -->
            <header class="h-12 px-4 flex items-center justify-between gap-2 border-b border-default shrink-0">
              <div class="flex items-center gap-2 min-w-0">
                <div
                  v-if="selectedChat"
                  class="flex items-center gap-2 min-w-0"
                >
                  <UAvatar
                    :src="selectedChat.avatar_url || undefined"
                    :alt="selectedChat.display_name"
                    size="2xs"
                    icon="i-lucide-user"
                  />
                  <span class="text-sm font-medium text-highlighted truncate">{{ selectedChat.display_name }}</span>
                </div>
              </div>

              <div class="flex items-center gap-2 shrink-0">
                <UBadge
                  :color="currentAiEnabled ? 'success' : 'warning'"
                  variant="subtle"
                  size="md"
                >
                  {{ currentAiEnabled ? 'AI Active' : 'AI Paused' }}
                </UBadge>
                <UButton
                  size="xs"
                  :color="currentAiEnabled ? 'warning' : 'primary'"
                  variant="solid"
                  :icon="currentAiEnabled ? 'i-lucide-pause-circle' : 'i-lucide-bot'"
                  :label="currentAiEnabled ? 'Take over' : 'Resume AI'"
                  :loading="togglingAi"
                  @click="toggleAi"
                />
              </div>
            </header>

            <!-- Messages -->
            <div
              ref="scroller"
              class="flex-1 overflow-y-auto px-4 py-4"
            >
              <USkeleton
                v-if="loadingMsgs"
                class="h-24 w-full"
              />
              <UChatMessages
                v-else
                :messages="rendered"
                :assistant="{ side: 'right', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
                :user="{ side: 'left', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
                :auto-scroll="false"
                should-scroll-to-bottom
              >
                <template #content="{ message }">
                  <!-- Toggle-driven system notice → centred separator -->
                  <USeparator
                    v-if="message.role === 'system'"
                    :label="systemLabel(message)"
                    class="my-1.5"
                    :ui="{ label: 'text-xs text-muted' }"
                  />
                  <div
                    v-else
                    class="flex flex-col gap-1 w-full"
                    :class="message.role === 'user' ? 'items-start' : 'items-end'"
                  >
                    <template
                      v-for="(block, i) in blocksFor(message)"
                      :key="i"
                    >
                      <!-- Payment card -->
                      <ChatPayCard
                        v-if="block.type === 'pay'"
                        :url="block.url"
                        :label="block.label"
                        :paid="isPaidDeal"
                      />

                      <!-- Payment link still streaming in -->
                      <div
                        v-else-if="block.type === 'pending'"
                        class="w-fit max-w-[85%] px-3.5 py-2 text-sm italic text-muted bg-elevated rounded-2xl rounded-bl-sm"
                      >
                        {{ $t('chat.preparingPayment') }}
                      </div>

                      <!-- Normal text bubble (preserved newlines) -->
                      <div
                        v-else
                        class="w-fit max-w-[85%] px-3.5 py-2 text-sm leading-relaxed rounded-2xl whitespace-pre-wrap break-words"
                        :class="message.role === 'user'
                          ? 'bg-elevated text-highlighted rounded-bl-sm'
                          : 'bg-secondary text-inverted rounded-br-sm'"
                      >
                        {{ block.text }}
                      </div>
                    </template>
                  </div>
                </template>
              </UChatMessages>

              <!-- Customer is typing (live via Supabase Realtime) -->
              <div
                v-if="!loadingMsgs && customerTyping"
                class="flex items-center gap-2 mt-2 text-sm text-muted"
              >
                <span class="flex gap-1">
                  <span class="size-1.5 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
                  <span class="size-1.5 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
                  <span class="size-1.5 rounded-full bg-current animate-bounce" />
                </span>
                <span>{{ $t('admin.chatsSection.typing') }}</span>
              </div>
            </div>

            <!-- Reply box -->
            <div class="border-t border-default p-3">
              <UChatPrompt
                v-model="reply"
                :loading="sending"
                placeholder="Reply as the seller…"
                @submit="send"
              >
                <UChatPromptSubmit
                  :status="sending ? 'streaming' : 'ready'"
                  color="primary"
                />
              </UChatPrompt>
            </div>
          </template>
        </section>
      </template>
    </USplitter>

    <!-- Mobile view (< md: 768px): Single pane Master-Detail navigation -->
    <div
      v-else
      class="flex-1 min-h-0 w-full flex flex-col overflow-hidden"
    >
      <!-- Conversation list on mobile -->
      <aside
        v-if="!selected"
        class="w-full h-full flex flex-col min-h-0 overflow-hidden"
      >
        <div class="h-12 px-3 flex items-center gap-2 border-b border-default shrink-0">
          <div class="flex-1 flex gap-0.5 p-0.5 rounded-md bg-elevated/50">
            <UButton
              v-for="f in filterItems"
              :key="f.value"
              size="xs"
              :color="filter === f.value ? 'primary' : 'neutral'"
              :variant="filter === f.value ? 'solid' : 'ghost'"
              class="flex-1 justify-center"
              :label="f.label"
              @click="filter = f.value"
            />
          </div>
          <UButton
            size="xs"
            variant="ghost"
            icon="i-lucide-refresh-cw"
            :loading="pending"
            @click="refresh()"
          />
        </div>

        <div class="px-3 py-2 flex items-center gap-2 border-b border-default shrink-0">
          <UInput
            v-model="search"
            size="xs"
            icon="i-lucide-search"
            class="flex-1"
            :placeholder="$t('admin.chatsSection.searchPlaceholder')"
            :aria-label="$t('admin.chatsSection.searchPlaceholder')"
          />
          <USelect
            v-model="sortKey"
            size="xs"
            :items="sortItems"
            class="w-32 shrink-0"
            :aria-label="$t('admin.chatsSection.sortLabel')"
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
            v-else-if="visibleChats.length === 0"
            :description="chats.length === 0 ? $t('admin.chatsSection.emptyList') : $t('admin.chatsSection.noMatch')"
            variant="naked"
            size="sm"
            class="p-6 text-center"
          />
          <div
            v-for="c in visibleChats"
            v-else
            :key="c.user_id"
            class="relative border-b border-default"
            :class="selected === c.user_id ? 'bg-elevated' : ''"
          >
            <button
              class="w-full text-left px-3 py-3 pr-16 hover:bg-elevated/50 transition-colors"
              @click="open(c.user_id)"
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

            <!-- SPEC-053: the read toggle sits OUTSIDE the row button (nesting one
                 button in another is invalid markup) so a thread can be dismissed
                 without being opened. -->
            <div class="absolute top-2.5 right-2 flex items-center gap-1.5">
              <UChip v-if="c.unread" />
              <UButton
                :data-testid="`chat-read-toggle-${c.user_id}`"
                size="xs"
                variant="ghost"
                color="neutral"
                :icon="c.unread ? 'i-lucide-mail-open' : 'i-lucide-mail'"
                :loading="markingRead === c.user_id"
                :aria-label="c.unread ? $t('admin.chatsSection.markRead') : $t('admin.chatsSection.markUnread')"
                :title="c.unread ? $t('admin.chatsSection.markRead') : $t('admin.chatsSection.markUnread')"
                @click="markRead(c.user_id, c.unread)"
              />
            </div>
          </div>
        </div>
      </aside>

      <!-- Thread view on mobile -->
      <section
        v-else
        class="w-full h-full min-w-0 flex flex-col min-h-0 overflow-hidden"
      >
        <!-- Mobile thread header with back button -->
        <header class="h-12 px-3 flex items-center justify-between gap-2 border-b border-default shrink-0">
          <div class="flex items-center gap-2 min-w-0">
            <UButton
              size="xs"
              variant="ghost"
              color="neutral"
              icon="i-lucide-arrow-left"
              label="Back"
              aria-label="Back to conversations"
              @click="selected = null"
            />
            <div
              v-if="selectedChat"
              class="flex items-center gap-1.5 min-w-0"
            >
              <UAvatar
                :src="selectedChat.avatar_url || undefined"
                :alt="selectedChat.display_name"
                size="2xs"
                icon="i-lucide-user"
              />
              <span class="text-xs font-medium text-highlighted truncate max-w-[90px]">{{ selectedChat.display_name }}</span>
            </div>
          </div>

          <div class="flex items-center gap-1.5 shrink-0">
            <UBadge
              :color="currentAiEnabled ? 'success' : 'warning'"
              variant="subtle"
              size="md"
            >
              {{ currentAiEnabled ? 'AI Active' : 'AI Paused' }}
            </UBadge>
            <UButton
              size="xs"
              :color="currentAiEnabled ? 'warning' : 'primary'"
              variant="solid"
              :icon="currentAiEnabled ? 'i-lucide-pause-circle' : 'i-lucide-bot'"
              :label="currentAiEnabled ? 'Take over' : 'Resume AI'"
              :loading="togglingAi"
              @click="toggleAi"
            />
          </div>
        </header>

        <!-- Messages -->
        <div
          ref="scroller"
          class="flex-1 overflow-y-auto px-3 py-3"
        >
          <USkeleton
            v-if="loadingMsgs"
            class="h-24 w-full"
          />
          <UChatMessages
            v-else
            :messages="rendered"
            :assistant="{ side: 'right', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
            :user="{ side: 'left', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
            :auto-scroll="false"
            should-scroll-to-bottom
          >
            <template #content="{ message }">
              <USeparator
                v-if="message.role === 'system'"
                :label="systemLabel(message)"
                class="my-1.5"
                :ui="{ label: 'text-xs text-muted' }"
              />
              <div
                v-else
                class="flex flex-col gap-1 w-full"
                :class="message.role === 'user' ? 'items-start' : 'items-end'"
              >
                <template
                  v-for="(block, i) in blocksFor(message)"
                  :key="i"
                >
                  <ChatPayCard
                    v-if="block.type === 'pay'"
                    :url="block.url"
                    :label="block.label"
                    :paid="isPaidDeal"
                  />

                  <div
                    v-else-if="block.type === 'pending'"
                    class="w-fit max-w-[85%] px-3.5 py-2 text-sm italic text-muted bg-elevated rounded-2xl rounded-bl-sm"
                  >
                    {{ $t('chat.preparingPayment') }}
                  </div>

                  <div
                    v-else
                    class="w-fit max-w-[85%] px-3.5 py-2 text-sm leading-relaxed rounded-2xl whitespace-pre-wrap break-words"
                    :class="message.role === 'user'
                      ? 'bg-elevated text-highlighted rounded-bl-sm'
                      : 'bg-secondary text-inverted rounded-br-sm'"
                  >
                    {{ block.text }}
                  </div>
                </template>
              </div>
            </template>
          </UChatMessages>

          <div
            v-if="!loadingMsgs && customerTyping"
            class="flex items-center gap-2 mt-2 text-sm text-muted"
          >
            <span class="flex gap-1">
              <span class="size-1.5 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
              <span class="size-1.5 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
              <span class="size-1.5 rounded-full bg-current animate-bounce" />
            </span>
            <span>{{ $t('admin.chatsSection.typing') }}</span>
          </div>
        </div>

        <!-- Reply box -->
        <div class="border-t border-default p-2.5">
          <UChatPrompt
            v-model="reply"
            :loading="sending"
            placeholder="Reply as seller…"
            @submit="send"
          >
            <UChatPromptSubmit
              :status="sending ? 'streaming' : 'ready'"
              color="primary"
            />
          </UChatPrompt>
        </div>
      </section>
    </div>
  </div>
</template>
