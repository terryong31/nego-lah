import { getUserCsrfToken, resolveUserId } from '~/utils/auth'

/**
 * One event, two audiences.
 *
 * SPEC-094 folded the chat's realtime channel into this stream, so what arrives
 * here is no longer only "someone messaged you": it is every event in the
 * buyer's conversation, including their own messages (echoed so the admin
 * console stays in sync) and typing pings. This composable toasts the subset
 * worth toasting; `useTypingChannel` renders the rest into the open chat.
 *
 * Subscribers live at module scope alongside the EventSource, because the
 * stream belongs to the session rather than to whichever component is mounted.
 */
export interface ChatStreamEvent {
  type?: string
  role?: string
  source?: string
  message?: string
  notify?: boolean
}

type ChatStreamHandler = (event: ChatStreamEvent) => void

const streamHandlers = new Set<ChatStreamHandler>()

/** Listen to the buyer's own conversation stream. Returns an unsubscribe. */
export function onChatStreamEvent(handler: ChatStreamHandler): () => void {
  streamHandlers.add(handler)
  return () => streamHandlers.delete(handler)
}

function fanOut(event: ChatStreamEvent) {
  for (const handler of [...streamHandlers]) {
    try {
      handler(event)
    } catch (err) {
      console.debug('A chat stream subscriber threw:', err)
    }
  }
}
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
let livenessTimer: ReturnType<typeof setInterval> | null = null
let routeWatchScope: ReturnType<typeof effectScope> | null = null
let authWatchScope: ReturnType<typeof effectScope> | null = null
let stamping: Promise<void> | null = null

// --- Reconnect backoff ----------------------------------------------------
// Every failure path in `openStream` used to end in a bare `return`, so one
// transient failure was permanent: the dev API restarting under `--reload`, a
// 502, a token that expired between the session read and the call. The stream
// dropped, the retry landed while the server was still booting, the mint failed
// — and that buyer had no notifications for the rest of the page's life. No
// toast, no chip, nothing until a reload, while `GET /chat/unread` went on
// answering correctly for anyone who refreshed, which is exactly what makes it
// look like a badge bug rather than a dead socket.
//
// The first retry is quick because most of these are a server coming back up;
// the ceiling is there so a genuinely unreachable API is not hammered.
const EVENT_SOURCE_CLOSED = 2
const RECONNECT_MIN_MS = 1000

// How often to check that the stream we think we have is a stream we still
// have. Every reconnect above is driven by an event — `onerror`, a rejected
// fetch — and none of them can fire for a connection that goes away quietly:
// a frozen tab, a socket closed underneath us, an error the browser swallowed.
// The server saw those subscriptions end. The client never heard. So something
// has to actually look, and this is the only path that does not depend on being
// told.
const LIVENESS_CHECK_MS = 15000
const RECONNECT_MAX_MS = 30000
let reconnectDelay = RECONNECT_MIN_MS

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

// Vite replaces this module on every edit, and the replacement starts with
// `eventSource = null` — so the stream the previous copy opened is orphaned:
// still connected, still holding one of the browser's six HTTP/1.1 sockets to
// the API, with nothing left that can close it. A handful of edits and new
// streams queue behind the dead ones until their 30-second tickets expire in
// the queue, which arrives as a 401 and reads exactly like a broken badge.
// Only dev pays this cost, and only dev can fix it.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    eventSource?.close()
    eventSource = null
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (livenessTimer) {
      clearInterval(livenessTimer)
      livenessTimer = null
    }
  })
}

export function useNotifications() {
  const config = useRuntimeConfig()
  const { user } = useAuth()
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
    if (!resolveUserId(user.value)) {
      return
    }
    try {
      await $fetch(`${config.public.apiBaseUrl}/chat/read`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': getUserCsrfToken() }
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
    if (!resolveUserId(user.value)) {
      return
    }
    try {
      const res = await $fetch<{ count?: number, has_unread?: boolean }>(
        `${config.public.apiBaseUrl}/chat/unread`,
        { credentials: 'include' }
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
    //
    // A CLOSED handle is not a connection, though. `onerror` normally clears it,
    // but a tab the OS froze and thawed can come back holding a dead
    // `EventSource` with no error event ever fired — and then this guard would
    // refuse every reconnect for the rest of the session on the strength of an
    // object that will never deliver anything again.
    if (eventSource) {
      if (eventSource.readyState !== EVENT_SOURCE_CLOSED) {
        return
      }
      disconnect()
    }
    if (connecting) {
      return connecting
    }

    connecting = openStream().finally(() => {
      connecting = null
    })
    return connecting
  }

  /**
   * Try again later, unless there is nothing to try for.
   *
   * Never gives up while the buyer is signed in: the alternative is a session
   * that silently stops being told anything.
   */
  function scheduleReconnect() {
    if (reconnectTimer || eventSource || !resolveUserId(user.value)) {
      return
    }
    const delay = reconnectDelay
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      // Re-checked, not assumed: the buyer can sign out between scheduling this
      // and it firing, and a stream opened for someone who left is worse than
      // no stream at all.
      if (!resolveUserId(user.value)) {
        return
      }
      void connect()
    }, delay)
  }

  async function openStream() {
    if (!resolveUserId(user.value)) {
      // Nobody to open a stream for. The watcher below calls back when that
      // changes; this covers the case where it doesn't.
      scheduleReconnect()
      return
    }

    // SPEC-056 #6 put a single-use ticket in this URL because `EventSource`
    // cannot set an `Authorization` header, and the access token it replaced was
    // being copied into the reverse proxy's access log, Cloudflare's, the
    // browser's history and the Referer of whatever the page loaded next.
    // SPEC-093 removed the need for either: the session is a cookie now, and
    // `withCredentials` is what sends it. The URL carries nothing at all.
    try {
      const streamUrl = `${config.public.apiBaseUrl}/chat/notifications/stream`
      eventSource = new EventSource(streamUrl, { withCredentials: true })

      eventSource.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data) as ChatStreamEvent

          // Hand every event to the chat page first — it renders the live
          // message and the typing indicator, and it needs the ones this
          // function goes on to ignore (SPEC-094).
          fanOut(data)

          // Typing pings, the buyer's own echoed messages and the system
          // separators all travel on this stream now, and none of them is
          // "someone messaged you". The server decides which are, and says so.
          if (data.type !== 'new_message' || data.notify !== true) {
            return
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

      // A stream that actually opened is proof the API is reachable, so the
      // next failure starts its backoff from scratch.
      eventSource.addEventListener('open', () => {
        reconnectDelay = RECONNECT_MIN_MS
      })

      eventSource.onerror = () => {
        // `EventSource` retries the URL by itself, but on its own schedule and
        // without the backoff below — and a 401 (revoked session) would have it
        // retrying forever. Close it and let `scheduleReconnect` decide.
        disconnect()
        scheduleReconnect()
      }

      // Catch up on whatever arrived while this session had no stream at all.
      void hydrate()
    } catch (err) {
      console.error('Failed to establish notification stream:', err)
      scheduleReconnect()
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

  // Connect when there is someone to connect for. Deliberately one-way: tearing
  // the stream down is the sign-out listener's job below, and it is the only
  // thing that can tell an actual sign-out from this ref reading null for a
  // moment.
  watch(
    () => resolveUserId(user.value),
    (uid) => {
      if (uid) {
        connect()
      }
    },
    { immediate: true }
  )

  // The one path that is not waiting to be told something. Anything else here
  // reacts to an event; a stream can end without producing one.
  if (import.meta.client && !livenessTimer) {
    livenessTimer = setInterval(() => {
      if (!resolveUserId(user.value)) {
        return
      }
      if (!eventSource || eventSource.readyState === EVENT_SOURCE_CLOSED) {
        void connect()
      }
    }, LIVENESS_CHECK_MS)
  }

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

  // Bound once per session: a watcher per composable call leaked both the
  // subscription and the closure holding its EventSource.
  //
  // One signal, not a stream of them. `@nuxtjs/supabase` used to emit plenty of
  // events carrying no session — a refresh in flight, a re-read on navigation —
  // and reading each one as "the buyer is gone" closed perfectly healthy
  // streams about four seconds before every send, which is exactly the shape of
  // "no toast, no chip, and a reload fixes it". The session ref only changes
  // when the session actually changes (SPEC-093), so there is nothing left to
  // disambiguate.
  if (import.meta.client && !authListenerBound) {
    authListenerBound = true
    // Detached, for the same reason the route watcher below is: a watcher
    // created in a component's setup is disposed when that component unmounts,
    // and `AppHeader` unmounts on every layout change. Bound once at module
    // scope but owned by the first component to ask, it would stop watching the
    // session the moment the buyer walked into /chat — and never rebind,
    // because the flag says it is already bound.
    authWatchScope = effectScope(true)
    authWatchScope.run(() => {
      watch(
        () => resolveUserId(user.value),
        (userId, previous) => {
          if (userId) {
            void connect()
            return
          }
          if (previous) {
            disconnect()
            clearUnread({ stamp: false })
          }
        }
      )
    })
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
