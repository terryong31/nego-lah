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

  function clearUnread() {
    hasUnread.value = false
    unreadCount.value = 0
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
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
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
          const isViewingChat = route.path === '/chat' && typeof document !== 'undefined' && !document.hidden
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
    } catch (err) {
      console.error('Failed to establish notification stream:', err)
    }
  }

  // Clear unread badge whenever user opens /chat
  watch(
    () => route.path,
    (path) => {
      if (path === '/chat') {
        clearUnread()
      }
    },
    { immediate: true }
  )

  // Re-connect when user auth state changes
  watch(
    () => user.value?.id,
    (uid) => {
      if (uid) {
        connect()
      } else {
        disconnect()
        clearUnread()
      }
    },
    { immediate: true }
  )

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
          clearUnread()
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
    connect,
    disconnect,
    requestNotificationPermission
  }
}
