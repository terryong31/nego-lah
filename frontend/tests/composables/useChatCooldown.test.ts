import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { useChatCooldown } from '../../app/composables/useChatCooldown'

/**
 * SPEC-043 workstream E.
 *
 * The buyer had no way to tell "I'm sending too fast" from "the AI is
 * thinking" from "something broke". This composable owns the first of those:
 * a countdown the input is gated on, plus the two softer signals (an early
 * warning, and a timed-out turn).
 *
 * The accessibility rules being asserted here are the ones that make a
 * countdown usable rather than maddening with a screen reader: `role="timer"`
 * is `aria-live="off"` by design, so the region must stay silent while the
 * number changes and speak only at the start and at the end.
 */

// Run inside an effect scope rather than a mounted component: the composable
// only needs reactivity (and a scope for its `onScopeDispose`), and a
// component instance would unwrap the refs this file asserts on.
let scope: ReturnType<typeof effectScope>

function mountCooldown() {
  return scope.run(() => useChatCooldown())!
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-07T12:00:00Z'))
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

describe('cooldown countdown', () => {
  it('starts idle, with the input free', async () => {
    const cooldown = mountCooldown()

    expect(cooldown.isCoolingDown.value).toBe(false)
    expect(cooldown.secondsLeft.value).toBe(0)
  })

  it('counts down and releases the input exactly when it reaches zero', async () => {
    const cooldown = mountCooldown()

    cooldown.start(5)
    expect(cooldown.isCoolingDown.value).toBe(true)
    expect(cooldown.secondsLeft.value).toBe(5)

    await vi.advanceTimersByTimeAsync(3000)
    expect(cooldown.secondsLeft.value).toBe(2)
    expect(cooldown.isCoolingDown.value).toBe(true)

    await vi.advanceTimersByTimeAsync(2000)
    expect(cooldown.secondsLeft.value).toBe(0)
    expect(cooldown.isCoolingDown.value).toBe(false)
  })

  it('never shows a negative countdown', async () => {
    const cooldown = mountCooldown()

    cooldown.start(2)
    await vi.advanceTimersByTimeAsync(10_000)

    expect(cooldown.secondsLeft.value).toBe(0)
  })

  it('recomputes from the clock, so a throttled background tab still ends on time', async () => {
    // A backgrounded tab has its timers throttled: far fewer ticks fire than
    // seconds pass. Counting ticks would leave the input locked long after the
    // server would accept a message again.
    const cooldown = mountCooldown()

    cooldown.start(30)

    // The clock jumps 25s while only one tick fires — exactly what a throttled
    // tab looks like.
    vi.setSystemTime(new Date('2026-09-07T12:00:25Z'))
    await vi.advanceTimersByTimeAsync(1000)

    // 26s of wall clock have really passed, so 4 remain. A tick-counting
    // implementation would still be sitting at 29 and would hold the input
    // locked for another half minute.
    expect(cooldown.secondsLeft.value).toBe(4)
  })

  it('takes the longer of two overlapping cooldowns rather than shortening one', async () => {
    const cooldown = mountCooldown()

    cooldown.start(30)
    cooldown.start(5)

    expect(cooldown.secondsLeft.value).toBe(30)
  })
})

describe('screen-reader announcements', () => {
  it('speaks when the cooldown starts and when it lifts, and stays silent in between', async () => {
    const cooldown = mountCooldown()
    const spoken: string[] = []

    // The live region renders `announcement`; every distinct non-empty value
    // is one thing a screen reader would say.
    let previous = cooldown.announcement.value
    const record = () => {
      if (cooldown.announcement.value !== previous) {
        previous = cooldown.announcement.value
        if (previous) spoken.push(previous)
      }
    }

    cooldown.start(4)
    record()

    for (let i = 0; i < 4; i++) {
      await vi.advanceTimersByTimeAsync(1000)
      record()
    }

    expect(spoken).toHaveLength(2)
    expect(spoken[0]).toBe('cooldownStarted')
    expect(spoken[1]).toBe('cooldownEnded')
  })
})

describe('the softer signals', () => {
  it('surfaces an early warning without gating the input', async () => {
    const cooldown = mountCooldown()

    cooldown.noteWarning(2)

    expect(cooldown.warningRemaining.value).toBe(2)
    expect(cooldown.isCoolingDown.value).toBe(false)
  })

  it('clears the early warning once the cooldown actually lands', async () => {
    const cooldown = mountCooldown()

    cooldown.noteWarning(1)
    cooldown.start(10)

    expect(cooldown.warningRemaining.value).toBe(null)
  })

  it('clears the warning when the buyer eases off', async () => {
    const cooldown = mountCooldown()

    cooldown.noteWarning(2)
    cooldown.clearWarning()

    expect(cooldown.warningRemaining.value).toBe(null)
  })

  it('flags a timed-out turn separately from a cooldown — it is not the buyer’s doing', async () => {
    const cooldown = mountCooldown()

    cooldown.noteTimeout()

    expect(cooldown.timedOut.value).toBe(true)
    expect(cooldown.isCoolingDown.value).toBe(false)

    cooldown.dismissTimeout()
    expect(cooldown.timedOut.value).toBe(false)
  })
})
