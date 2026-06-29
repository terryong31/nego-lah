import type { RealtimeChannel } from '@supabase/supabase-js'

interface JoinOptions {
  /** The role broadcast by the *other* party that we want to react to. */
  listenFor: 'customer' | 'seller'
  /** The role we broadcast as. */
  sendAs: 'customer' | 'seller'
  /** Optional auth token (the customer side is logged in; the admin side isn't). */
  accessToken?: string
  /** Callback for real-time messages (e.g. system messages on AI toggle) */
  onMessage?: (payload: unknown) => void
}

/**
 * Shared "is the other person typing" presence over a Supabase Realtime broadcast
 * channel, keyed per conversation (`chat:<userId>`). Used by both the customer
 * chat page and the admin console so the two sides speak the same protocol.
 *
 * Key correctness points (the reasons the naive version didn't work):
 *  - `channel.send()` is a no-op until the channel reaches SUBSCRIBED, so we gate
 *    every outgoing ping on a `ready` flag set from the subscribe() callback.
 *  - We surface the subscription status to the console so a project-level problem
 *    (Realtime disabled / blocked) is distinguishable from a code bug.
 */
export function useTypingChannel() {
  const supabase = useSupabaseClient()

  const remoteTyping = ref(false)

  let channel: RealtimeChannel | null = null
  let ready = false
  let sendRole: JoinOptions['sendAs'] = 'customer'
  let lastSent = 0
  let clearTimer: ReturnType<typeof setTimeout> | null = null

  function leave() {
    if (clearTimer) {
      clearTimeout(clearTimer)
      clearTimer = null
    }
    if (channel) {
      supabase.removeChannel(channel)
      channel = null
    }
    ready = false
    remoteTyping.value = false
  }

  function join(conversationId: string, opts: JoinOptions) {
    leave()
    sendRole = opts.sendAs

    // Make sure the realtime socket authenticates with the logged-in user's JWT
    // (harmless on the anon admin client; required if the project ever switches
    // these to private channels).
    if (opts.accessToken) {
      try {
        supabase.realtime.setAuth(opts.accessToken)
      } catch {
        // best effort — public channels don't require this
      }
    }

    channel = supabase.channel(`chat:${conversationId}`, {
      config: { broadcast: { self: false } }
    })

    channel
      .on('broadcast', { event: 'typing' }, ({ payload }: { payload?: { role?: string } }) => {
        if (payload?.role !== opts.listenFor) return
        remoteTyping.value = true
        // Broadcasts carry no "stopped typing" signal — expire after an idle window.
        if (clearTimer) clearTimeout(clearTimer)
        clearTimer = setTimeout(() => {
          remoteTyping.value = false
        }, 3000)
      })
      .on('broadcast', { event: 'new_message' }, ({ payload }) => {
        if (opts.onMessage) opts.onMessage(payload)
      })
      .subscribe((status) => {
        ready = status === 'SUBSCRIBED'
        if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
          console.warn(`[typing] realtime channel "chat:${conversationId}" ${status} — is Realtime enabled for this Supabase project?`)
        }
      })
  }

  /** Tell the other side we're typing (throttled; dropped until subscribed). */
  function ping() {
    if (!channel || !ready) return
    const now = Date.now()
    if (now - lastSent < 1500) return
    lastSent = now
    channel.send({ type: 'broadcast', event: 'typing', payload: { role: sendRole } })
  }

  onUnmounted(leave)

  return { remoteTyping, join, ping, leave }
}
