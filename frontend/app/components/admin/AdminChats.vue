<script setup lang="ts">
const { call } = useAdminApi()
const toast = useToast()

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

// Read/unread filter for the conversation list.
type ChatFilter = 'all' | 'unread' | 'read'
const filter = ref<ChatFilter>('all')
const filterItems = [
  { label: 'All', value: 'all' as const },
  { label: 'Unread', value: 'unread' as const },
  { label: 'Read', value: 'read' as const }
]
const filteredChats = computed(() =>
  chats.value.filter((c) => {
    if (filter.value === 'unread') return c.unread
    if (filter.value === 'read') return !c.unread
    return true
  })
)

const messages = ref<ChatMessage[]>([])
const loadingMsgs = ref(false)
const reply = ref('')
const sending = ref(false)
const scroller = ref<HTMLElement | null>(null)

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
  joinTyping(userId, {
    listenFor: 'customer',
    sendAs: 'seller',
    onMessage: (payload) => {
      const msg = payload as { content?: string, role?: string, source?: string }
      if (!msg || !msg.content) return
      messages.value.push({
        role: msg.role === 'system' ? 'system' : (msg.role ?? 'ai'),
        content: msg.content,
        source: msg.source
      })
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

const PAY_LINK = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/

type Block
  = | { type: 'text', text: string }
    | { type: 'pay', label: string, url: string }
    | { type: 'pending' }

function messageBlocks(message: RenderedMessage): Block[] {
  const text = getMessageText(message)
  return text
    .split('\n')
    .map((l: string) => l.trim())
    .filter((l: string) => l.length > 0)
    .map((line: string): Block => {
      const m = line.match(PAY_LINK)
      if (m) return { type: 'pay', label: m[1]!, url: m[2]! }
      if (line.includes('](http')) return { type: 'pending' }
      return { type: 'text', text: line }
    })
}
</script>

<template>
  <div class="flex flex-1 min-h-0">
    <!-- Conversation list -->
    <aside class="w-72 shrink-0 border-r border-default flex flex-col">
      <div class="h-12 px-3 flex items-center gap-2 border-b border-default">
        <div class="flex-1 flex gap-0.5 p-0.5 rounded-md bg-elevated/50">
          <button
            v-for="f in filterItems"
            :key="f.value"
            class="flex-1 text-xs font-medium rounded px-2 py-1 transition-colors"
            :class="filter === f.value ? 'bg-primary text-inverted' : 'text-muted hover:text-default'"
            @click="filter = f.value"
          >
            {{ f.label }}
          </button>
        </div>
        <UButton
          size="xs"
          variant="ghost"
          icon="i-lucide-refresh-cw"
          :loading="pending"
          @click="refresh()"
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
        <div
          v-else-if="filteredChats.length === 0"
          class="p-6 text-center text-sm text-muted"
        >
          {{ chats.length === 0 ? 'No conversations yet.' : 'No conversations match this filter.' }}
        </div>
        <button
          v-for="c in filteredChats"
          v-else
          :key="c.user_id"
          class="w-full text-left px-3 py-3 border-b border-default hover:bg-elevated/50 transition-colors"
          :class="selected === c.user_id ? 'bg-elevated' : ''"
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
            <UChip
              v-if="c.unread"
              class="ml-auto"
            />
          </div>
          <p class="text-sm text-default truncate">
            {{ c.last_message || '—' }}
          </p>
          <p class="text-xs text-dimmed">
            {{ c.message_count }} messages
          </p>
        </button>
      </div>
    </aside>

    <!-- Conversation thread -->
    <section class="flex-1 min-w-0 flex flex-col">
      <div
        v-if="!selected"
        class="flex-1 flex flex-col items-center justify-center text-center text-muted gap-2"
      >
        <UIcon
          name="i-lucide-messages-square"
          class="size-10"
        />
        <p class="text-sm">
          Select a conversation to view and reply.
        </p>
      </div>

      <template v-else>
        <!-- Thread header -->
        <header class="h-12 px-4 flex items-center gap-2 border-b border-default">
          <UButton
            class="ml-auto"
            size="xs"
            variant="ghost"
            color="neutral"
            icon="i-lucide-x"
            @click="selected = null"
          />
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
            <!-- Carousell-style: each line break renders as its own bubble -->
            <template #content="{ message }">
              <!-- Toggle-driven system notice → centred separator, not a bubble -->
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
                  v-for="(block, i) in messageBlocks(message)"
                  :key="i"
                >
                  <!-- Payment link → call-to-action box -->
                  <div
                    v-if="block.type === 'pay'"
                    class="w-fit max-w-[90%] rounded-2xl rounded-bl-sm border border-secondary/30 bg-secondary/5 p-4 flex flex-col gap-3"
                  >
                    <div class="flex items-center gap-2.5">
                      <span class="flex items-center justify-center size-9 rounded-lg bg-secondary/10 shrink-0">
                        <UIcon
                          name="i-simple-icons-stripe"
                          class="size-4.5 text-secondary"
                        />
                      </span>
                      <div class="min-w-0">
                        <p class="text-sm font-semibold text-highlighted leading-tight">
                          Payment ready
                        </p>
                        <p class="text-xs text-muted leading-tight">
                          Complete your purchase securely via Stripe
                        </p>
                      </div>
                    </div>
                    <UButton
                      :to="block.url"
                      target="_blank"
                      rel="noopener noreferrer"
                      :label="block.label || 'Pay now'"
                      color="secondary"
                      icon="i-lucide-external-link"
                      trailing
                      block
                    />
                  </div>

                  <!-- Payment link still streaming in -->
                  <div
                    v-else-if="block.type === 'pending'"
                    class="w-fit max-w-[85%] px-3.5 py-2 text-sm italic text-muted bg-elevated rounded-2xl rounded-bl-sm"
                  >
                    Preparing payment link…
                  </div>

                  <!-- Normal text bubble -->
                  <div
                    v-else
                    class="w-fit max-w-[85%] px-3.5 py-2 text-sm leading-relaxed rounded-2xl"
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
            <span>Customer is typing…</span>
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
  </div>
</template>
