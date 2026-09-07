<script setup lang="ts">
import { useChat } from '@ai-sdk/vue'
import { DefaultChatTransport } from 'ai'
import { loginRedirect } from '~/utils/auth'
import { useItemStore } from '~/stores/item'

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
const { locale, t } = useI18n()

const accessToken = ref('')

// Optional item context: when the customer arrives from an item's "Negotiate"
// button we pass that item_id along so the AI knows what's being discussed.
// It is NOT a separate room — there is a single conversation per customer.
const contextItemId = computed(() => (route.query.item_id as string) || '')

// SPEC-041: one fetch per session; SSE discount events patch the store in place.
const itemStore = useItemStore()

interface ChatItem {
  item_id: string
  name: string
  price: number
  discounted_price?: number
  status: string
  images?: string
  translations?: Record<string, ItemTranslation>
}

// contextItem is driven by the store so it updates reactively when applyDiscount
// patches discountedPrice — no extra ref needed.
const contextItem = computed<ChatItem | null>(() => {
  if (!contextItemId.value) return null
  const state = itemStore.getItem(contextItemId.value)
  if (!state) return null
  const { item, discountedPrice } = state
  return {
    ...item,
    discounted_price: discountedPrice ?? item.discounted_price
  } as ChatItem
})

// The pinned item shows the listing in the reader's language, same as the
// item page — the raw `name` is whatever the seller typed.
const contextItemName = computed(() =>
  localizedItemField(contextItem.value, locale.value, 'name')
)

// Whether the AI still answers this conversation. When the seller takes over
// (chat_settings.ai_enabled = false) the backend saves the buyer's message and
// closes the stream without a reply, so showing "Cooking…" promises an answer
// that is never coming.
const aiEnabled = ref(true)

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

// SPEC-043: the three "please wait" states — a hard cooldown the input gates
// on, the heads-up before it, and a turn that ran out of time.
const cooldown = useChatCooldown()

// The last thing the buyer typed, so a timed-out turn can be retried without
// making them type it again.
const lastSentText = ref('')

/**
 * The server answers a cooldown with 429 + `Retry-After`. Intercepting it here
 * rather than in `onError` keeps the AI SDK out of it entirely: the SDK would
 * surface a bare Error with no access to the header or the body, so the UI
 * could say "something went wrong" but never "wait 12 seconds".
 *
 * An empty-but-well-formed stream goes back in its place, so `useChat` settles
 * cleanly instead of leaving the composer stuck mid-send.
 */
async function fetchWithCooldown(input: RequestInfo | URL, init?: RequestInit) {
  const response = await globalThis.fetch(input, init)
  if (response.status !== 429) return response

  const headerSeconds = Number(response.headers.get('Retry-After'))
  let bodySeconds = Number.NaN
  try {
    const body = await response.clone().json()
    bodySeconds = Number(body?.detail?.retryAfterSeconds)
  } catch {
    // A proxy may have rewritten the body; the header alone is enough.
  }

  const seconds = [bodySeconds, headerSeconds].find(n => Number.isFinite(n) && n > 0)
  cooldown.start(seconds ?? 60)

  return new Response(
    'data: {"type":"start"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
    {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'x-vercel-ai-ui-message-stream': 'v1'
      }
    }
  )
}

const { messages, status, stop, sendMessage } = useChat({
  transport: new DefaultChatTransport({
    api: `${config.public.apiBaseUrl}/chat/stream`,
    fetch: fetchWithCooldown,
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
  }),
  // SPEC-041: handle the real-time discount signal from the SSE stream.
  // `onData` is a `useChat` option, not a transport one -- it's invoked once
  // per data part the stream emits (never as an array), so this must live
  // here rather than nested inside `DefaultChatTransport`'s options, where
  // the AI SDK would never call it at all.
  onData(dataPart) {
    const p = dataPart as {
      type?: string
      id?: string
      data?: { discounted_price?: number, remaining?: number }
    }
    if (p.type === 'data-discount' && p.id === 'discount' && contextItemId.value) {
      const price = p.data?.discounted_price
      if (typeof price === 'number') {
        itemStore.applyDiscount(contextItemId.value, price)
      }
    }

    // SPEC-043: nearing the per-minute cooldown. Nothing is blocked yet — this
    // exists so the block, when it comes, isn't a surprise.
    if (p.type === 'data-cooldown-warning') {
      const remaining = p.data?.remaining
      if (typeof remaining === 'number') cooldown.noteWarning(remaining)
    }

    // The turn ran past its deadline. Not the buyer's doing, so it gets a
    // retry rather than a countdown.
    if (p.type === 'data-turn-timeout') {
      cooldown.noteTimeout()
    }
  }
})

// Holds ONLY the agent's own [[STATUS:…]] text, which the backend emits in
// English. Empty means "no tool running", and the indicator then falls back to
// the translated `chat.thinking` label rather than a hardcoded English word.
const aiStatusText = ref('')

// A turn that is merely slow is not the buyer's fault and must not gate their
// input — it only changes what the existing indicator says. The threshold is
// well past a normal turn, so ordinary latency never trips it.
const SLOW_TURN_AFTER_MS = 8000
const turnTakingLong = ref(false)
let slowTurnTimer: ReturnType<typeof setTimeout> | null = null

function clearSlowTurnTimer() {
  if (slowTurnTimer !== null) {
    clearTimeout(slowTurnTimer)
    slowTurnTimer = null
  }
}

watch(status, (newStatus) => {
  if (newStatus === 'submitted') {
    aiStatusText.value = ''
  }

  if (newStatus === 'submitted' || newStatus === 'streaming') {
    if (slowTurnTimer === null) {
      slowTurnTimer = setTimeout(() => {
        turnTakingLong.value = true
      }, SLOW_TURN_AFTER_MS)
    }
  } else {
    clearSlowTurnTimer()
    turnTakingLong.value = false
  }
})

onBeforeUnmount(clearSlowTurnTimer)

// The composable stays language-agnostic and reports *what* happened; the
// wording lives here with the rest of the copy.
const cooldownAnnouncement = computed(() => {
  if (cooldown.announcement.value === 'cooldownStarted') {
    return t('chat.cooldown.slowDown', { seconds: cooldown.secondsLeft.value })
  }
  if (cooldown.announcement.value === 'cooldownEnded') {
    return t('chat.cooldown.canSendAgain')
  }
  return ''
})

// While cooling down, the indicator label is the countdown itself.
const promptPlaceholder = computed(() =>
  cooldown.isCoolingDown.value
    ? t('chat.cooldown.waitingPlaceholder', { seconds: cooldown.secondsLeft.value })
    : t('chat.placeholder')
)

const indicatorText = computed(() => {
  if (sellerTyping.value) return t('chat.sellerTyping')
  if (aiStatusText.value) return aiStatusText.value
  if (turnTakingLong.value) return t('chat.cooldown.takingLonger')
  return t('chat.thinking')
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
  parts?: { type: string, text?: string, data?: unknown }[]
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
      parts: [
        { type: 'text' as const, text: m.content ?? m.message ?? '' },
        // SPEC-027: 'admin' (seller takeover) vs 'ai' decides whether this
        // message's newlines are bubble boundaries or just line breaks.
        ...(m.source ? [{ type: 'data-source' as const, data: m.source }] : [])
      ]
    }))
    .filter(m => (m.parts[0] as { text: string }).text.trim().length > 0)
}

function scrollToBottom() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}

// True while the agent is mid-stream but has only emitted [[STATUS:…]] markers
// and no real reply text yet — i.e. it's still running tools.
const aiWorking = computed(() => {
  if (!aiEnabled.value) return false
  if (status.value !== 'streaming') return false
  const last = messages.value[messages.value.length - 1]
  if (!last || last.role !== 'assistant') return false
  return getMessageText(last).trim().length === 0
})

// What we actually hand to <UChatMessages>. While the agent is still working,
// blank out the live assistant bubble's parts so UChatMessages keeps showing
// its *own* thinking indicator (the #indicator slot) instead of an empty bubble.
// This way the shimmer never moves between DOM nodes — the same indicator that
// said "Thinking…" simply updates its text to each status — and there's no
// second <article> for the theme's last-of-type min-height to stretch.
const displayMessages = computed(() => {
  if (!aiWorking.value) return messages.value
  return messages.value.map((m, i) =>
    i === messages.value.length - 1 && m.role === 'assistant'
      ? { ...m, parts: [] }
      : m
  )
})

// The status we hand to <UChatMessages>. The Nuxt UI indicator shows whenever
// status === 'submitted', so we force that while the seller is typing — the
// indicator renders on the assistant (left/seller) side, exactly where we want
// "the seller is typing…" to appear — while leaving the AI's own streaming
// status untouched the rest of the time.
const effectiveStatus = computed(() => {
  if (sellerTyping.value) return 'submitted'
  // With the AI paused there is nothing to wait on but the seller.
  if (!aiEnabled.value) return 'ready'
  return status.value
})

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

        // Customer already has their own message rendered locally
        if (msg.source === 'human' || msg.role === 'user') return

        // If useChat is actively streaming an AI turn, ignore AI broadcast to prevent double bubble
        if (msg.source === 'ai' && (status.value === 'streaming' || status.value === 'submitted')) return

        // A system separator means the AI was just handed over or handed back.
        if (msg.role === 'system' || msg.source === 'system') {
          loadChatSettings()
        }

        // Push the new message into the view
        messages.value.push({
          id: globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2),
          role: (msg.role === 'system' || msg.source === 'system') ? 'system' : (msg.role as 'user' | 'assistant'),
          parts: [
            { type: 'text', text: msg.content },
            ...(msg.source ? [{ type: 'data-source' as const, data: msg.source }] : [])
          ]
        })
        scrollToBottom()
      }
    })
  }

  await Promise.all([
    contextItemId.value ? itemStore.fetchIfMissing(contextItemId.value) : Promise.resolve(),
    loadChatSettings()
  ])
})

// The header price mirrors what the buyer would actually pay right now. The
// backend derives `discounted_price` from the negotiated offer it caches per
// (user, item), so every finished agent turn can move it — refetch once the
// stream settles instead of leaving a stale listed price on screen.
// Reflects a takeover the moment it happens: the backend broadcasts a system
// separator ("Terry has joined the chat…") on both sides of the toggle, so any
// system message is the cue to re-read the setting.
async function loadChatSettings() {
  const uid = await currentUserId()
  if (!uid) return
  try {
    const res = await call<{ ai_enabled?: boolean }>(`/chat/settings/${uid}`)
    aiEnabled.value = res?.ai_enabled !== false
  } catch { /* leave the AI assumed on — the worst case is a stale indicator */ }
}

// SPEC-041: per-turn item refetch removed. The store is seeded once on mount
// and updated reactively via the data-discount SSE handler above.
// Only chat settings need a refresh when a stream ends (ai_enabled toggle).
watch(status, (now, before) => {
  if ((before === 'streaming' || before === 'submitted') && now !== 'streaming' && now !== 'submitted') {
    loadChatSettings()
  }
})

async function send(text: string) {
  const trimmed = text.trim()
  if (!trimmed) return

  // Always send a fresh, valid token (the cached ref can be empty/expired,
  // which makes the stream endpoint return 401).
  const { data: { session } } = await supabase.auth.getSession()

  // No session left to refresh: the buyer was logged out by inactivity while
  // sitting on this page. Posting anyway would just 401 the stream and look
  // like the message vanished, so bounce to login carrying this chat's URL
  // (item_id included) — they come straight back here after signing in.
  if (!session?.access_token) {
    toast.add({
      title: t('auth.sessionExpired'),
      description: t('auth.sessionExpiredDesc'),
      color: 'warning'
    })
    await supabase.auth.signOut()
    await navigateTo(loginRedirect(route.fullPath))
    return
  }

  accessToken.value = session.access_token

  input.value = ''
  lastSentText.value = trimmed
  cooldown.dismissTimeout()
  startTyping()
  await sendMessage({ text: trimmed })
}

function onSubmit() {
  if (cooldown.isCoolingDown.value) return
  send(input.value)
}

// A timed-out turn produced no reply, so resending the same message is the
// whole recovery — no need to make the buyer retype it.
function retryLastTurn() {
  const text = lastSentText.value
  if (!text || cooldown.isCoolingDown.value) return
  cooldown.dismissTimeout()
  send(text)
}

function getMessageText(message: UIMessageLike) {
  if (!message?.parts) return ''
  const text = message.parts
    .filter(p => p.type === 'text')
    .map(p => p.text)
    .join('')

  // Return the pure text without magic strings
  return text.replace(/\[\[STATUS:.*?\]\]/g, '')
}

// Watch messages purely to extract status strings safely outside of render cycle
watch(() => messages.value, (newMsgs) => {
  if (newMsgs.length > 0) {
    const lastMsg = newMsgs[newMsgs.length - 1]
    if (lastMsg?.role === 'assistant' && lastMsg.parts) {
      const rawText = lastMsg.parts
        .filter(p => p.type === 'text')
        .map(p => p.text)
        .join('')

      const statusMatches = rawText.match(/\[\[STATUS:(.*?)\]\]/g)
      if (statusMatches && statusMatches.length > 0) {
        const lastMatch = statusMatches[statusMatches.length - 1]
        if (lastMatch) {
          aiStatusText.value = lastMatch.replace('[[STATUS:', '').replace(']]', '')
        }
      }
    }
  }
}, { deep: true })

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

// The assistant bubble the typewriter is (or is about to be) revealing. While
// the stream is live this is ALWAYS the last assistant message, so the bubble
// shows the progressively-typed text from its very first frame — otherwise the
// full server response renders for one tick before `typeTick` assigns typingId,
// which is the "fully rendered message flashes for a split second" glitch. Once
// the stream ends we fall back to typingId so the reveal can finish naturally.
const typingMessageId = computed(() => {
  if (status.value === 'streaming' || status.value === 'submitted') {
    const last = messages.value[messages.value.length - 1]
    if (last?.role === 'assistant') return last.id
  }
  return typingId.value
})

// SPEC-027: which engine authored this message's newlines. History rows and
// realtime pushes carry the stored `source`; a live-streamed turn has none,
// which `shouldSplit` reads as the AI.
function messageSource(message: UIMessageLike): string | undefined {
  const part = (message.parts ?? []).find(p => p.type === 'data-source')
  return typeof part?.data === 'string' ? part.data : undefined
}

// The bubbles one message renders as. Passing the typewriter's partial text
// means bubbles pop into existence one at a time as newlines are uncovered.
function blocksFor(message: UIMessageLike) {
  const text = message.id === typingMessageId.value ? shownText.value : getMessageText(message)
  return messageBlocks(text, shouldSplit(message.role, messageSource(message)))
}

const isPaidDeal = computed(() => {
  if (contextItem.value?.status === 'sold') return true
  return messages.value.some((m) => {
    const txt = getMessageText(m)
    return txt.includes('Payment Confirmed') || txt.includes('Thank you for purchasing')
  })
})

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
      class="flex items-center gap-2.5 sm:gap-3 px-3 sm:px-4 py-2.5 sm:py-3 border-b border-default bg-default"
    >
      <NuxtLink
        :to="`/items/${contextItem.item_id}`"
        class="shrink-0"
      >
        <img
          v-if="contextImage"
          :src="contextImage"
          :alt="contextItemName"
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
            {{ contextItemName }}
          </p>
        </NuxtLink>
        <div
          v-if="hasDiscount(contextItem)"
          class="flex items-baseline gap-1.5 flex-wrap"
        >
          <p class="text-base font-bold text-primary">
            {{ formatPrice(effectivePrice(contextItem)) }}
          </p>
          <p class="text-xs line-through text-muted">
            {{ formatPrice(contextItem.price) }}
          </p>
          <UBadge
            color="primary"
            variant="subtle"
            size="sm"
            :label="`-${discountPercent(contextItem)}%`"
          />
        </div>
        <p
          v-else
          class="text-base font-bold text-highlighted"
        >
          {{ formatPrice(contextItem.price) }}
        </p>
      </div>

      <UButton
        v-if="contextItem.status !== 'sold'"
        :label="$t('items.buyNow')"
        color="primary"
        :loading="buyLoading"
        class="shrink-0"
        @click="handleBuyNow"
      />
      <UBadge
        v-else
        color="neutral"
        variant="subtle"
        size="lg"
        :label="$t('items.status.sold')"
        class="shrink-0 font-semibold"
      />
    </div>

    <!-- Messages -->
    <div
      ref="scroller"
      class="flex-1 min-h-0 overflow-y-auto px-2.5 sm:px-4 py-3 sm:py-5"
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
      <UEmpty
        v-else-if="!messages.length"
        icon="i-lucide-messages-square"
        :description="$t('chat.emptyDesc')"
        variant="naked"
        class="h-full justify-center px-6"
      />

      <!-- Conversation (official Nuxt UI chat components) -->
      <div v-else>
        <div
          v-if="hasMore"
          class="flex justify-center pb-4"
        >
          <UButton
            :label="$t('chat.loadOlder')"
            icon="i-lucide-chevron-up"
            color="neutral"
            variant="ghost"
            size="xs"
            :loading="loadingMore"
            @click="loadMore"
          />
        </div>

        <UChatMessages
          :messages="displayMessages"
          :status="effectiveStatus"
          should-auto-scroll
          auto-scroll
          :user="{ side: 'right', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
          :assistant="{ side: 'left', variant: 'naked', ui: { root: 'w-full', container: 'w-full', body: 'w-full', content: 'w-full' } }"
        >
          <!-- Work-process indicator: a single, fixed-height ChatTool row that
               shimmers and just swaps its (truncated) label as the agent moves
               from "Cooking…" to "Searching the market…" etc. Because the label
               truncates on one line, changing status never reflows the height or
               spawns a scrollbar, and it never hops between DOM nodes.

               No `loading` prop: that swaps in appConfig.ui.icons.loading and
               stamps `animate-spin` on the leading icon, which would clobber
               both the brand mark and its hop. The icon + `ui` props are the
               supported way to restyle it — ChatTool exposes no leading slot. -->
          <template #indicator>
            <UChatTool
              :text="indicatorText"
              :icon="sellerTyping ? 'i-lucide-store' : 'i-nego-mark'"
              :ui="sellerTyping ? undefined : { leadingIcon: 'animate-brand-hop text-default' }"
              streaming
            />
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
                v-for="(block, i) in blocksFor(message)"
                :key="i"
              >
                <!-- Payment link → checkout hand-off card -->
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

                <!-- Normal text bubble with line-breaks preserved -->
                <div
                  v-else
                  class="w-fit max-w-[85%] px-3.5 py-2 text-sm leading-relaxed rounded-2xl break-words whitespace-pre-wrap"
                  :class="message.role === 'user'
                    ? 'bg-primary text-inverted rounded-br-sm'
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
    <div class="px-2.5 sm:px-4 py-2 sm:py-3 bg-default">
      <!-- SPEC-043: the wait states sit with the composer, because they are
           about the act of sending — not things the assistant said. They are
           never rendered as chat bubbles. -->

      <!-- A turn that ran out of time. Nothing broke and nothing is blocked,
           so this offers a retry rather than a countdown. -->
      <UAlert
        v-if="cooldown.timedOut.value"
        :title="$t('chat.cooldown.turnTimedOut')"
        icon="i-lucide-clock"
        color="neutral"
        variant="subtle"
        class="mb-2"
        :ui="{ title: 'text-xs', root: 'py-2' }"
      >
        <template #actions>
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :label="$t('chat.cooldown.tryAgain')"
            @click="retryLastTurn"
          />
        </template>
      </UAlert>

      <!-- Approaching the cooldown. Advisory only — the composer stays live. -->
      <p
        v-else-if="cooldown.warningRemaining.value !== null && !cooldown.isCoolingDown.value"
        class="mb-2 px-1 text-xs text-muted"
      >
        {{ $t('chat.cooldown.almostAtLimit', { count: cooldown.warningRemaining.value }) }}
      </p>

      <!-- The cooldown itself. `role="timer"` is implicitly aria-live="off",
           which is what keeps the ticking number from being read out every
           second; the separate live region below speaks only at the two
           moments that matter. -->
      <div
        v-if="cooldown.isCoolingDown.value"
        role="timer"
        class="mb-2 flex items-center gap-2 px-1 text-xs text-muted"
      >
        <UIcon
          name="i-lucide-hourglass"
          class="size-3.5 shrink-0"
        />
        <span>
          {{ $t('chat.cooldown.slowDown', { seconds: cooldown.secondsLeft.value }) }}
        </span>
      </div>

      <!-- Announces once when the wait starts and once when it lifts. -->
      <p
        aria-live="polite"
        class="sr-only"
      >
        {{ cooldownAnnouncement }}
      </p>

      <UChatPrompt
        v-model="input"
        :placeholder="promptPlaceholder"
        :disabled="cooldown.isCoolingDown.value"
        variant="subtle"
        class="rounded-xl"
        @submit="onSubmit"
      >
        <UChatPromptSubmit
          :status="status"
          :disabled="cooldown.isCoolingDown.value"
          color="primary"
          @stop="stop"
        />
      </UChatPrompt>
    </div>
  </div>
</template>
