<script setup lang="ts">
import { useChat } from '@ai-sdk/vue'
import { DefaultChatTransport } from 'ai'

definePageMeta({
  layout: 'chat',
  middleware: 'auth'
})

const PAGE_SIZE = 20

const { call } = useApi()
const route = useRoute()
const config = useRuntimeConfig()
const user = useSupabaseUser()
const supabase = useSupabaseClient()
const toast = useToast()

const accessToken = ref('')

// Optional item context: when the customer arrives from an item's "Negotiate"
// button we pass that item_id along so the AI knows what's being discussed.
// It is NOT a separate room — there is a single conversation per customer.
const contextItemId = computed(() => (route.query.item_id as string) || '')

interface ChatItem {
  item_id: string
  name: string
  price: number
  status: string
  images?: string
}
const contextItem = ref<ChatItem | null>(null)

const input = ref('')
const loadingHistory = ref(true)
const loadingMore = ref(false)
const hasMore = ref(false)
const offset = ref(0)
const scroller = ref<HTMLElement | null>(null)
const buyLoading = ref(false)

// --- Live typing presence (Supabase Realtime broadcast) -------------------
// The seller (admin console) broadcasts `typing` events on a per-conversation
// channel during a human takeover; we surface that as the chat's typing
// indicator, and broadcast the customer's own typing back the other way.
const { remoteTyping: sellerTyping, join: joinTyping, ping: pingTyping } = useTypingChannel()

const { messages, status, stop, sendMessage } = useChat({
  transport: new DefaultChatTransport({
    api: `${config.public.apiBaseUrl}/chat/stream`,
    headers: () => ({
      Authorization: `Bearer ${accessToken.value}`
    }),
    prepareSendMessagesRequest: ({ messages: sdkMessages, body }) => {
      const last = sdkMessages[sdkMessages.length - 1]
      const text = (last?.parts ?? [])
        .filter(p => p.type === 'text')
        .map(p => p.text)
        .join('')

      return {
        body: {
          ...body,
          message: text,
          user_id: user.value?.id,
          item_id: contextItemId.value || null
        }
      }
    }
  })
})

function uid() {
  return globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)
}

interface StoredMessage {
  id?: string
  role?: string
  source?: string
  content?: string
  message?: string
}

interface ChatHistoryResponse {
  messages?: StoredMessage[]
  next_offset?: number
  has_more?: boolean
}

interface UIMessageLike {
  id?: string
  role?: string
  parts?: { type: string, text?: string }[]
}

// Map stored history messages → SDK UI messages, dropping empties.
function mapMessages(list?: StoredMessage[]) {
  return (list ?? [])
    .map(m => ({
      id: m.id || uid(),
      role: m.role === 'human'
        ? ('user' as const)
        : (m.role === 'system' || m.source === 'system')
            ? ('system' as const)
            : ('assistant' as const),
      parts: [{ type: 'text' as const, text: m.content ?? m.message ?? '' }]
    }))
    .filter(m => m.parts[0]!.text.trim().length > 0)
}

function scrollToBottom() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}

// The status we hand to <UChatMessages>. The Nuxt UI indicator shows whenever
// status === 'submitted', so we force that while the seller is typing — the
// indicator renders on the assistant (left/seller) side, exactly where we want
// "the seller is typing…" to appear — while leaving the AI's own streaming
// status untouched the rest of the time.
const effectiveStatus = computed(() => (sellerTyping.value ? 'submitted' : status.value))

// Surface the seller's typing the moment it starts.
watch(sellerTyping, (typing) => {
  if (typing) scrollToBottom()
})

watch(input, (val) => {
  if (val.trim()) pingTyping()
})

async function currentUserId(): Promise<string | null> {
  if (user.value?.id) return user.value.id
  // user ref can lag on a hard refresh — fall back to the session directly.
  const { data: { session } } = await supabase.auth.getSession()
  return session?.user?.id ?? null
}

async function loadInitial() {
  const uid = await currentUserId()
  if (!uid) {
    loadingHistory.value = false
    return
  }
  loadingHistory.value = true
  try {
    const res = await call<ChatHistoryResponse>(`/chat/history/${uid}?limit=${PAGE_SIZE}&offset=0`)
    messages.value = mapMessages(res?.messages)
    offset.value = res?.next_offset ?? messages.value.length
    hasMore.value = !!res?.has_more
    scrollToBottom()
  } catch (err) {
    console.error('Error loading chat history:', err)
  } finally {
    loadingHistory.value = false
  }
}

async function loadMore() {
  if (!hasMore.value || loadingMore.value) return
  const uid = await currentUserId()
  if (!uid) return
  loadingMore.value = true
  const prevHeight = scroller.value?.scrollHeight ?? 0
  try {
    const res = await call<ChatHistoryResponse>(`/chat/history/${uid}?limit=${PAGE_SIZE}&offset=${offset.value}`)
    const older = mapMessages(res?.messages)
    messages.value = [...older, ...messages.value]
    offset.value = res?.next_offset ?? offset.value + older.length
    hasMore.value = !!res?.has_more
    // Preserve the reading position after prepending older messages.
    nextTick(() => {
      if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight - prevHeight
    })
  } catch (err) {
    toast.add({ title: 'Failed to load older messages', description: err instanceof Error ? err.message : 'Something went wrong', color: 'error' })
  } finally {
    loadingMore.value = false
  }
}

onMounted(async () => {
  const { data: { session } } = await supabase.auth.getSession()
  accessToken.value = session?.access_token || ''

  supabase.auth.onAuthStateChange((_event, session) => {
    accessToken.value = session?.access_token || ''
  })

  await loadInitial()

  const uid = await currentUserId()
  if (uid) {
    joinTyping(uid, {
      listenFor: 'seller',
      sendAs: 'customer',
      accessToken: accessToken.value,
      onMessage: (payload) => {
        const msg = payload as { content?: string, role?: string, source?: string }
        // Drop any empty messages just to be safe
        if (!msg || !msg.content) return

        // Push the new message into the view
        messages.value.push({
          id: globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2),
          role: (msg.role === 'system' || msg.source === 'system') ? 'system' : (msg.role as 'user' | 'assistant'),
          parts: [{ type: 'text', text: msg.content }]
        })
        scrollToBottom()
      }
    })
  }

  if (contextItemId.value) {
    try {
      contextItem.value = await call<ChatItem>(`/items/${contextItemId.value}`)
    } catch { /* item may be gone — context header just won't show */ }
  }
})

async function send(text: string) {
  const trimmed = text.trim()
  if (!trimmed) return

  // Always send a fresh, valid token (the cached ref can be empty/expired,
  // which makes the stream endpoint return 401).
  const { data: { session } } = await supabase.auth.getSession()
  accessToken.value = session?.access_token || ''

  input.value = ''
  startTyping()
  await sendMessage({ text: trimmed })
}

function onSubmit() {
  send(input.value)
}

function getMessageText(message: UIMessageLike) {
  if (!message?.parts) return ''
  return message.parts
    .filter(p => p.type === 'text')
    .map(p => p.text)
    .join('')
}

// System notices (e.g. the AI takeover toggle) come wrapped in dashes:
// "--- Terry has joined the chat, the AI will retire for now ---". Strip them
// so the bare text sits cleanly in the middle of a separator.
function systemLabel(message: UIMessageLike) {
  return getMessageText(message).replace(/^[\s-]+|[\s-]+$/g, '')
}

// --- Client-side typewriter illusion ---------------------------------------
// The server sends the reply quickly; we reveal it character-by-character here
// so it reads like the AI is generating in real time.
const CHAR_RATE = 50 // characters per second
const shownText = ref('')
const typingId = ref<string | null>(null)
let typeTimer: ReturnType<typeof setInterval> | null = null

function typeTick() {
  const last = messages.value[messages.value.length - 1]
  if (!last || last.role !== 'assistant') {
    if (status.value !== 'streaming' && status.value !== 'submitted') stopTyping()
    return
  }
  const target = getMessageText(last)
  if (!target) return
  typingId.value = last.id
  if (shownText.value.length < target.length) {
    // Reveal one more character.
    shownText.value = target.slice(0, shownText.value.length + 1)
    scrollToBottom()
  } else if (status.value !== 'streaming' && status.value !== 'submitted') {
    // Fully revealed and the stream has finished — hand back to plain rendering.
    stopTyping()
  }
}

function startTyping() {
  shownText.value = ''
  typingId.value = null
  if (typeTimer) clearInterval(typeTimer)
  typeTimer = setInterval(typeTick, 1000 / CHAR_RATE)
}

function stopTyping() {
  if (typeTimer) {
    clearInterval(typeTimer)
    typeTimer = null
  }
  typingId.value = null
  shownText.value = ''
}

onUnmounted(stopTyping)

// Detects a markdown link the agent emits for payment, e.g.
// "[Pay RM71.50 Now](https://buy.stripe.com/...)".
const PAY_LINK = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/

type Block
  = | { type: 'text', text: string }
    | { type: 'pay', label: string, url: string }
    | { type: 'pending' }

// Carousell-style: each line break becomes its own block. While a reply is
// being typed out, the active message shows its progressively-revealed text.
// Markdown payment links render as a dedicated "pay" box instead of raw text.
function messageBlocks(message: UIMessageLike): Block[] {
  const text = message.id === typingId.value ? shownText.value : getMessageText(message)
  return text
    .split('\n')
    .map((l: string) => l.trim())
    .filter((l: string) => l.length > 0)
    .map((line: string): Block => {
      const m = line.match(PAY_LINK)
      if (m) return { type: 'pay', label: m[1]!, url: m[2]! }
      // Link still being typed out — hold a placeholder until it's complete.
      if (line.includes('](http')) return { type: 'pending' }
      return { type: 'text', text: line }
    })
}

const contextImage = computed(() => {
  if (!contextItem.value?.images) return null
  try {
    const arr = JSON.parse(contextItem.value.images)
    return Array.isArray(arr) && arr.length ? arr[0] : null
  } catch { return null }
})

async function handleBuyNow() {
  if (!contextItem.value) return
  buyLoading.value = true
  try {
    const res = await call<{ checkout_url?: string }>('/payment/checkout', {
      method: 'POST',
      body: { item_id: contextItem.value.item_id, user_id: user.value?.id }
    })
    if (res?.checkout_url) {
      window.location.href = res.checkout_url
    } else {
      throw new Error('No checkout URL returned')
    }
  } catch (err) {
    toast.add({ title: 'Checkout failed', description: err instanceof Error ? err.message : 'Unable to start transaction', color: 'error' })
  } finally {
    buyLoading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col h-full w-full">
    <!-- Item header (Carousell-style) -->
    <div
      v-if="contextItem"
      class="flex items-center gap-3 px-4 py-3 border-b border-default bg-default"
    >
      <NuxtLink
        :to="`/items/${contextItem.item_id}`"
        class="shrink-0"
      >
        <img
          v-if="contextImage"
          :src="contextImage"
          :alt="contextItem.name"
          class="size-14 rounded-lg object-cover bg-muted"
        >
        <div
          v-else
          class="size-14 rounded-lg bg-muted flex items-center justify-center"
        >
          <UIcon
            name="i-lucide-image"
            class="size-5 text-muted"
          />
        </div>
      </NuxtLink>

      <div class="flex-1 min-w-0">
        <NuxtLink
          :to="`/items/${contextItem.item_id}`"
          class="block"
        >
          <p class="text-sm font-semibold text-highlighted truncate hover:text-primary transition-colors">
            {{ contextItem.name }}
          </p>
        </NuxtLink>
        <p class="text-base font-bold text-highlighted">
          RM {{ contextItem.price?.toFixed(2) }}
        </p>
      </div>

      <UButton
        v-if="contextItem.status !== 'sold'"
        label="Buy"
        color="primary"
        :loading="buyLoading"
        class="shrink-0"
        @click="handleBuyNow"
      />
      <UBadge
        v-else
        color="neutral"
        variant="subtle"
        label="Sold"
        class="shrink-0"
      />
    </div>

    <!-- Messages -->
    <div
      ref="scroller"
      class="flex-1 min-h-0 overflow-y-auto px-4 py-5"
    >
      <!-- Loading skeletons -->
      <div
        v-if="loadingHistory"
        class="space-y-5"
      >
        <USkeleton
          v-for="i in 4"
          :key="i"
          class="h-12 rounded-lg"
          :class="i % 2 ? 'w-2/3' : 'w-2/5 ml-auto'"
        />
      </div>

      <!-- Empty state -->
      <div
        v-else-if="!messages.length"
        class="h-full flex flex-col items-center justify-center text-center text-muted gap-3 px-6"
      >
        <UIcon
          name="i-lucide-messages-square"
          class="size-10"
        />
        <p class="text-sm max-w-xs">
          Send a message to start negotiating. Make an offer or ask about the item — the AI will haggle with you.
        </p>
      </div>

      <!-- Conversation (official Nuxt UI chat components) -->
      <div v-else>
        <div
          v-if="hasMore"
          class="flex justify-center pb-4"
        >
          <UButton
            label="Load older messages"
            icon="i-lucide-chevron-up"
            color="neutral"
            variant="ghost"
            size="xs"
            :loading="loadingMore"
            @click="loadMore"
          />
        </div>

        <UChatMessages
          :messages="messages"
          :status="effectiveStatus"
          should-auto-scroll
          :auto-scroll="false"
          :user="{ side: 'right', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
          :assistant="{ side: 'left', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
        >
          <!-- Shimmer while waiting for the first token, or while the seller types -->
          <template #indicator>
            <UChatShimmer :text="sellerTyping ? 'Seller is typing…' : 'Thinking…'" />
          </template>

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
              class="flex flex-col gap-1"
              :class="message.role === 'user' ? 'items-end' : 'items-start'"
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
                    ? 'bg-secondary text-inverted rounded-br-sm'
                    : 'bg-elevated text-highlighted rounded-bl-sm'"
                >
                  {{ block.text }}
                </div>
              </template>
            </div>
          </template>
        </UChatMessages>
      </div>
    </div>

    <!-- Input -->
    <div class="px-4 py-3 border-t border-default bg-default">
      <UChatPrompt
        v-model="input"
        placeholder="Type here..."
        variant="subtle"
        class="rounded-xl"
        @submit="onSubmit"
      >
        <UChatPromptSubmit
          :status="status"
          color="primary"
          @stop="stop"
        />
      </UChatPrompt>
    </div>
  </div>
</template>
