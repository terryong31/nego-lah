// --- Session-wide stream state -------------------------------------------
// The notification stream belongs to the browser session, not to whichever
// component happens to be mounted. `AppHeader` re-mounts on every layout change
// (default -> chat -> dashboard), and each mount used to open its OWN
// EventSource in a fresh closure that nothing ever closed. The backend broker
// fans each message out to every subscribed queue, so after a few navigations
// one seller message arrived as five identical toasts.
//
// Keeping the connection (and the auth listener) at module scope means one
// stream per session no matter how many times the composable is called.
let eventSource: EventSource | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let connecting: Promise<void> | null = null
let authListenerBound = false
let visibilityListenerBound = false
let routeWatchScope: ReturnType<typeof effectScope> | null = null
let stamping: Promise<void> | null = null

// --- Route matching ------------------------------------------------------
// Cloudflare Pages serves this SPA from the directory form of a route, so a
// hard load (or a link followed from an email) settles the chat page on
// `/chat/?item_id=…` — and vue-router reports `route.path` exactly as the URL
// spells it, trailing slash included. An `=== '/chat'` comparison therefore
// missed the one case it existed for: the user got toasted about messages that
// were already on screen in front of them.
function isChatPath(path: string | undefined): boolean {
  if (!path) {
    return false
  }
  return path.split('?')[0]!.split('#')[0]!.replace(/\/+$/, '') === '/chat'
}

export function useNotifications() {
  const config = useRuntimeConfig()
  const user = useSupabaseUser()
  const supabase = useSupabaseClient()
  const route = useRoute()
  const toast = useToast()

  const hasUnread = useState<boolean>('notifications:hasUnread', () => false)
  const unreadCount = useState<number>('notifications:unreadCount', () => 0)

  async function requestNotificationPermission() {
    if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
      try {
        await Notification.requestPermission()
      } catch {
        // best effort
      }
    }
  }

  /** The buyer's Supabase access token, or null when there is no session. */
  async function accessToken(): Promise<string | null> {
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token ?? null
  }

  /**
   * Clear the badge, and tell the server the conversation was read.
   *
   * SPEC-061: the badge used to be a `useState` that only an incoming SSE event
   * ever wrote, so it meant "messages this tab watched arrive" rather than
   * "messages you haven't read". Clearing it therefore had nothing to persist.
   * Now every real read event moves a watermark the next cold load reads back.
   *
   * `stamp: false` is the sign-out path — a user who just left has no session
   * to write with and nothing to record.
   */
  function clearUnread({ stamp = true }: { stamp?: boolean } = {}) {
    const hadUnread = hasUnread.value || unreadCount.value > 0
    hasUnread.value = false
    unreadCount.value = 0

    // Standing on the chat page IS the read event, whether or not a chip
    // happened to be showing when it happened.
    if (stamp && (hadUnread || isChatPath(route.path))) {
      void stampRead()
    }
  }

  /**
   * One write per read event, not one per mounted component.
   *
   * The badge is session state but the composable is per-caller, so every
   * component that asks for it registers its own route watcher — and a single
   * navigation then asks every one of them to stamp, in the same tick. The
   * watermark is the same instant whichever of them wins, so they can share the
   * request the first one made.
   */
  function stampRead(): Promise<void> {
    if (stamping) {
      return stamping
    }
    stamping = writeReadWatermark().finally(() => {
      stamping = null
    })
    return stamping
  }

  async function writeReadWatermark() {
    const token = await accessToken()
    if (!token) {
      return
    }
    try {
      await $fetch(`${config.public.apiBaseUrl}/chat/read`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      })
    } catch (err) {
      // The badge is already clear on screen; a failed write means it comes
      // back on the next load, which is the honest outcome.
      console.debug('Could not stamp the chat read watermark:', err)
    }
  }

  /**
   * Seed the badge from the server. This is the only path that knows about
   * messages which landed while no tab was open — no SSE event ever fired for
   * them, so without this the header is clean and the reply sits unread in a
   * transcript nothing points at.
   */
  async function hydrate() {
    if (!import.meta.client) {
      return
    }
    // They are looking at the conversation right now; anything in it is read.
    if (isChatPath(route.path) && typeof document !== 'undefined' && !document.hidden) {
      return
    }
    const token = await accessToken()
    if (!token) {
      return
    }
    try {
      const res = await $fetch<{ count?: number, has_unread?: boolean }>(
        `${config.public.apiBaseUrl}/chat/unread`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      unreadCount.value = res?.count ?? 0
      hasUnread.value = Boolean(res?.has_unread)
    } catch (err) {
      // A chip is not worth breaking the header over.
      console.debug('Could not read the unread count:', err)
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  async function connect() {
    if (!import.meta.client) {
      return
    }
    // Already streaming, or a connect is mid-flight: nothing to do. Without
    // this guard every caller (each mount, each auth event) opened a duplicate.
    if (eventSource) {
      return
    }
    if (connecting) {
      return connecting
    }

    connecting = openStream().finally(() => {
      connecting = null
    })
    return connecting
  }

  async function openStream() {
    const token = await accessToken()
    if (!token) {
      return
    }

    // SPEC-056 #6. `EventSource` cannot set headers, which is why this used to
    // append the Supabase access token to the URL — where it was copied into the
    // reverse proxy's access log, Cloudflare's, the browser's history and the
    // Referer of whatever the page loaded next, all for a credential good for
    // the next hour of API calls. So the token stays in a header on this POST,
    // and the URL carries a ticket that is worth one stream for thirty seconds.
    let ticket: string
    try {
      const minted = await $fetch<{ ticket: string }>(
        `${config.public.apiBaseUrl}/chat/notifications/ticket`,
        { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
      )
      ticket = minted.ticket
    } catch (err) {
      console.error('Could not mint a notification stream ticket:', err)
      return
    }

    try {
      const streamUrl = `${config.public.apiBaseUrl}/chat/notifications/stream?ticket=${encodeURIComponent(ticket)}`
      eventSource = new EventSource(streamUrl)

      eventSource.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data) as {
            type?: string
            message?: string
            source?: string
          }

          // If user is currently actively viewing /chat (tab is active), don't show notifications
          const isViewingChat = isChatPath(route.path) && typeof document !== 'undefined' && !document.hidden
          if (isViewingChat) {
            clearUnread()
            return
          }

          hasUnread.value = true
          unreadCount.value++

          const isSeller = data.source === 'admin'
          const senderTitle = isSeller ? 'New message from Seller' : 'New message from Nego-Lah'
          const messageText = data.message || 'You received a new message.'

          toast.add({
            title: senderTitle,
            description: messageText,
            icon: 'i-lucide-message-square',
            color: 'primary'
          })

          // Browser Notification API for backgrounded/minimized tabs
          if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
            try {
              new Notification(senderTitle, {
                body: messageText,
                icon: '/icon-192.png'
              })
            } catch {
              // Notification API error swallowed
            }
          }
        } catch (err) {
          console.error('Error parsing notification event:', err)
        }
      })

      eventSource.onerror = () => {
        disconnect()
        // Retry connection after 5 seconds if user is still logged in
        if (user.value?.id) {
          reconnectTimer = setTimeout(connect, 5000)
        }
      }

      // Catch up on whatever arrived while this session had no stream at all.
      // After the ticket, deliberately: a stream that cannot be opened is the
      // one case where the reconnect timer will bring us back here anyway.
      void hydrate()
    } catch (err) {
      console.error('Failed to establish notification stream:', err)
    }
  }

  // Arriving at the conversation reads it; so does leaving it.
  //
  // The stamp on arrival can only ever cover what was already there, and the
  // buyer's own turn is answered *after* it — by the chat page's own stream,
  // which never goes near the notification stream, so nothing else moves the
  // watermark past the reply. Chat with the agent, walk back to the storefront,
  // reload, and a chip appears for a message the buyer watched arrive. Leaving
  // the page covers everything that landed while they were on it.
  //
  // In a detached scope, and for the same reason the stream is at module scope:
  // `/chat` has its own layout, so leaving it unmounts the header that owns
  // this watcher and mounts a fresh one. Vue disposes a component's pre-flush
  // watchers when it unmounts and the layout swap renders first, so a watcher
  // belonging to the header never runs for the one transition it is here for —
  // the leaving half was dead on arrival while it lived in the component.
  if (!routeWatchScope) {
    routeWatchScope = effectScope(true)
    routeWatchScope.run(() => {
      watch(
        () => route.path,
        (path, previous) => {
          if (isChatPath(path)) {
            clearUnread()
          } else if (isChatPath(previous)) {
            void stampRead()
          }
        },
        { immediate: true }
      )
    })
  }

  // Re-connect when user auth state changes
  watch(
    () => user.value?.id,
    (uid) => {
      if (uid) {
        connect()
      } else {
        disconnect()
        clearUnread({ stamp: false })
      }
    },
    { immediate: true }
  )

  // A tab the buyer left and came back to has missed everything that happened
  // while it was hidden — including its own stream dropping. Re-ask.
  if (import.meta.client && !visibilityListenerBound && typeof document !== 'undefined') {
    visibilityListenerBound = true
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        // The other way out of the conversation: the tab goes to the
        // background with the reply on screen. Same read, same stamp.
        if (isChatPath(route.path)) {
          void stampRead()
        }
        return
      }
      // `hydrate` is a no-op without a session, so there is nothing to guard
      // here that it doesn't guard better.
      void hydrate()
    })
  }

  // Bound once per session: a listener per composable call leaked both the
  // subscription and the closure holding its EventSource.
  if (import.meta.client && !authListenerBound) {
    authListenerBound = true
    try {
      supabase.auth.onAuthStateChange((_event, session) => {
        if (session?.user) {
          connect()
        } else {
          disconnect()
          clearUnread({ stamp: false })
        }
      })
    } catch {
      authListenerBound = false
      // safe fallback if supabase is not initialized
    }
  }

  return {
    hasUnread,
    unreadCount,
    clearUnread,
    hydrate,
    connect,
    disconnect,
    requestNotificationPermission
  }
}
