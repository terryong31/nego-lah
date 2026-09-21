import { onChatStreamEvent, type ChatStreamEvent } from '~/composables/useNotifications'
import { getCsrfToken } from '~/composables/useAdminApi'
import { getUserCsrfToken } from '~/utils/auth'

interface JoinOptions {
  /** The role broadcast by the *other* party that we want to react to. */
  listenFor: 'customer' | 'seller'
  /** The role we broadcast as. */
  sendAs: 'customer' | 'seller'
  /** Callback for real-time messages (e.g. system messages on AI toggle) */
  onMessage?: (payload: ChatStreamEvent) => void
}

/**
 * Shared "is the other person typing" presence, keyed per conversation. Used by
 * both the customer chat page and the admin console so the two sides speak the
 * same protocol.
 *
 * SPEC-094 moved that protocol off Supabase Realtime. The channel it used —
 * `chat:{userId}`, created with no `private: true` and with no policy on
 * `realtime.messages` — was public: the anon key ships in this bundle, so
 * anyone holding it and a user id could subscribe and read that buyer's
 * negotiation as it happened. The events now travel on the same authenticated
 * SSE stream the notifications use, per user, and a ping is an ordinary POST.
 *
 * The two sides differ only in which session authorises them:
 *  - the buyer rides the stream `useNotifications` already holds open, and pings
 *    `POST /chat/typing`, which reads the conversation off their own session so
 *    there is no id to tamper with.
 *  - the admin console opens its own stream against the admin cookie.
 */
export function useTypingChannel() {
  const config = useRuntimeConfig()

  const remoteTyping = ref(false)

  let detach: (() => void) | null = null
  let adminSource: EventSource | null = null
  let sendRole: JoinOptions['sendAs'] = 'customer'
  let conversation: string | null = null
  let lastSent = 0
  let clearTimer: ReturnType<typeof setTimeout> | null = null

  function leave() {
    if (clearTimer) {
      clearTimeout(clearTimer)
      clearTimer = null
    }
    if (detach) {
      detach()
      detach = null
    }
    if (adminSource) {
      adminSource.close()
      adminSource = null
    }
    conversation = null
    remoteTyping.value = false
  }

  function join(conversationId: string, opts: JoinOptions) {
    leave()
    sendRole = opts.sendAs
    conversation = conversationId

    const handle = (payload: ChatStreamEvent) => {
      if (payload?.type === 'typing') {
        // Our own ping comes back down the same stream (one channel per
        // conversation, both parties on it), so the role is what tells them
        // apart — exactly as it did on the old broadcast channel.
        if (payload.role !== opts.listenFor) return
        remoteTyping.value = true
        // Typing carries no "stopped" signal — expire after an idle window.
        if (clearTimer) clearTimeout(clearTimer)
        clearTimer = setTimeout(() => {
          remoteTyping.value = false
        }, 3000)
        return
      }
      if (payload?.type === 'new_message' && opts.onMessage) {
        opts.onMessage(payload)
      }
    }

    if (opts.sendAs === 'customer') {
      detach = onChatStreamEvent(handle)
      return
    }

    // Admin console: its own stream, on the admin session.
    const url = `${config.public.apiBaseUrl}/admin/chats/${encodeURIComponent(conversationId)}/stream`
    adminSource = new EventSource(url, { withCredentials: true })
    adminSource.addEventListener('message', (event) => {
      try {
        handle(JSON.parse(event.data) as ChatStreamEvent)
      } catch (err) {
        console.debug('Could not parse an admin chat event:', err)
      }
    })
    adminSource.onerror = () => {
      console.warn(`[typing] admin stream for "${conversationId}" dropped`)
    }
  }

  /** Tell the other side we're typing (throttled; dropped when not joined). */
  function ping() {
    if (!conversation) return
    const now = Date.now()
    if (now - lastSent < 1500) return
    lastSent = now

    const isAdmin = sendRole === 'seller'
    const url = isAdmin
      ? `${config.public.apiBaseUrl}/admin/chats/${encodeURIComponent(conversation)}/typing`
      : `${config.public.apiBaseUrl}/chat/typing`

    // Fire and forget: a typing ping that fails is not worth a retry, a toast
    // or a log line — by the time anyone noticed, it would be stale anyway.
    void $fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Token': isAdmin ? getCsrfToken() : getUserCsrfToken() }
    }).catch(() => {})
  }

  onUnmounted(leave)

  return { remoteTyping, join, ping, leave }
}
