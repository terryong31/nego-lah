/**
 * SPEC-043 workstream E — the chat's "please wait" states.
 *
 * Three distinct situations that used to be indistinguishable to a buyer:
 *
 *  - **cooldown** — they sent too fast and the server is refusing for N
 *    seconds. Their doing, so the input gates and a countdown says how long.
 *  - **warning** — they're close to that wall. Worth a heads-up so hitting it
 *    is never a surprise, but nothing is blocked yet.
 *  - **timed out** — a turn ran past its deadline. Not their doing at all, so
 *    it gets a retry rather than a countdown, and never blames them.
 *
 * The countdown recomputes from the wall clock on every tick instead of
 * decrementing a counter. A backgrounded tab has its timers throttled to a
 * fraction of a tick per second, so a decrementing counter would hold the
 * input locked long after the server would have accepted a message again.
 */
export function useChatCooldown() {
  const deadlineAt = ref<number | null>(null)
  const now = ref(Date.now())
  const warningRemaining = ref<number | null>(null)
  const timedOut = ref(false)
  const announcement = ref('')

  let ticker: ReturnType<typeof setInterval> | null = null

  const secondsLeft = computed(() => {
    if (deadlineAt.value === null) return 0
    return Math.max(0, Math.ceil((deadlineAt.value - now.value) / 1000))
  })

  const isCoolingDown = computed(() => secondsLeft.value > 0)

  function stopTicking() {
    if (ticker !== null) {
      clearInterval(ticker)
      ticker = null
    }
  }

  function tick() {
    now.value = Date.now()
    if (secondsLeft.value > 0) return

    // Landed. Release the input and say so once — this is the only
    // announcement between the start and here.
    stopTicking()
    deadlineAt.value = null
    announcement.value = 'cooldownEnded'
  }

  /**
   * Gate the input for `seconds`, taken from the server's `Retry-After`.
   *
   * A second cooldown arriving mid-count extends but never shortens: the
   * server is the authority on when it will accept again, and taking the
   * shorter of two would re-enable the input early and earn another rejection.
   */
  function start(seconds: number) {
    const candidate = Date.now() + Math.max(0, seconds) * 1000
    if (deadlineAt.value !== null && candidate <= deadlineAt.value) return

    deadlineAt.value = candidate
    now.value = Date.now()
    warningRemaining.value = null
    announcement.value = 'cooldownStarted'

    stopTicking()
    ticker = setInterval(tick, 1000)
  }

  function noteWarning(remaining: number) {
    if (isCoolingDown.value) return
    warningRemaining.value = remaining
  }

  function clearWarning() {
    warningRemaining.value = null
  }

  function noteTimeout() {
    timedOut.value = true
  }

  function dismissTimeout() {
    timedOut.value = false
  }

  onScopeDispose(stopTicking)

  return {
    secondsLeft,
    isCoolingDown,
    warningRemaining,
    timedOut,
    announcement,
    start,
    noteWarning,
    clearWarning,
    noteTimeout,
    dismissTimeout
  }
}
