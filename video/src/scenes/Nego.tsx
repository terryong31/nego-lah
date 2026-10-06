import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { pop, progress } from '../motion'
import { Arch, Burst, Squiggle } from '../shapes'
import { C, SLAM, UI, hardShadow } from '../theme'
import { NEGO } from '../timeline'
import { Avatar, PriceTag } from '../ui/parts'
import { SlamText } from '../ui/SlamText'

/**
 * The haggle. Buyer on the left, agent on the right, and the asking price on
 * its tag stepping down — whole ringgit, small steps, holding well clear of a
 * floor that is never on screen.
 */

const ROW = 134

const Bubble = ({ index }: { index: number }) => {
  const frame = useCurrentFrame()
  const msg = NEGO.messages[index]!
  const s = pop(frame, msg.at, SLAM)
  const agent = msg.from === 'agent'

  return (
    <div
      style={{
        position: 'absolute',
        top: 70 + index * ROW,
        left: agent ? undefined : 90,
        right: agent ? 1920 - 1000 : undefined,
        display: 'flex',
        flexDirection: agent ? 'row-reverse' : 'row',
        alignItems: 'center',
        gap: 18,
        transform: `scale(${s}) translateX(${(1 - s) * (agent ? 120 : -120)}px)`,
        transformOrigin: agent ? 'right center' : 'left center'
      }}
    >
      <Avatar kind={agent ? 'agent' : 'buyer'} size={84} />
      <div
        style={{
          padding: '20px 34px',
          borderRadius: agent ? '34px 34px 8px 34px' : '34px 34px 34px 8px',
          border: `6px solid ${C.ink}`,
          background: agent ? C.green : C.paper,
          boxShadow: hardShadow(8, agent ? C.ink : C.pink),
          fontFamily: UI,
          fontWeight: 700,
          fontSize: 46,
          color: C.ink,
          whiteSpace: 'nowrap'
        }}
      >
        {msg.text}
      </div>
    </div>
  )
}

/** Three dots, bouncing, while the agent decides. */
const Typing = ({ at }: { at: number }) => {
  const frame = useCurrentFrame()
  const t = frame - (at - NEGO.typing)
  if (t < 0 || t >= NEGO.typing) return null
  const index = NEGO.messages.findIndex(m => m.at === at)

  return (
    <div
      style={{
        position: 'absolute',
        top: 70 + index * ROW + 16,
        right: 1920 - 1000 + 104,
        display: 'flex',
        gap: 10,
        padding: '20px 26px',
        borderRadius: 34,
        border: `6px solid ${C.ink}`,
        background: C.paper
      }}
    >
      {[0, 1, 2].map(i => (
        <div
          key={i}
          style={{
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: C.ink,
            transform: `translateY(${Math.sin((t - i * 3) / 2.2) * -8}px)`
          }}
        />
      ))}
    </div>
  )
}

export const Nego = () => {
  const frame = useCurrentFrame()

  const counters = NEGO.messages.filter(m => 'price' in m) as { at: number, price: number }[]
  const history = [{ at: 0, price: NEGO.startPrice }, ...counters]
  const current = [...history].reverse().find(h => frame >= h.at + 4) ?? history[0]!
  const bump = pop(frame, current.at + 4, SLAM)
  const wiggle = Math.sin(frame / 6) * 2

  return (
    <AbsoluteFill style={{ background: C.paper, overflow: 'hidden' }}>
      <Squiggle size={240} color={C.cyan} style={{ left: 1590, top: 960, transform: `translateX(${wiggle * 6}px)` }} />
      <Arch size={120} style={{ left: 1040, top: 40 }} />
      <Burst size={110} color={C.purple} style={{ left: 1760, top: 520, transform: `rotate(${frame * 1.5}deg)` }} />

      {/* The divider between the chat and the price. */}
      <div style={{ position: 'absolute', left: 1080, top: 0, bottom: 0, width: 6, background: C.ink }} />

      {NEGO.messages.map((_, i) => <Bubble key={i} index={i} />)}
      {NEGO.messages.filter(m => m.from === 'agent').map(m => <Typing key={m.at} at={m.at} />)}

      <div style={{ position: 'absolute', left: 1170, top: 110 }}>
        <SlamText text="The AI" at={NEGO.title} size={150} color={C.ink} shadow={C.yellow} />
        <SlamText text="haggles." at={NEGO.title + 6} size={150} color={C.ink} shadow={C.pink} style={{ marginTop: 4 }} />
      </div>

      <PriceTag
        price={current.price}
        size={1.5}
        color={C.yellow}
        style={{
          left: 1190,
          top: 520,
          transform: `rotate(${-6 + wiggle}deg) scale(${0.85 + 0.15 * bump})`
        }}
      />

      {/* The struck-through trail of earlier asks. */}
      <div style={{ position: 'absolute', left: 1210, top: 790, display: 'flex', gap: 34 }}>
        {history.slice(0, -1).map((h, i) => {
          // An ask joins the trail when the next one replaces it, then gets struck.
          const replaced = history[i + 1]!.at + 4
          if (frame < replaced) return null
          const s = pop(frame, replaced)
          const strike = progress(frame, replaced + 6, replaced + 14)
          return (
            <div
              key={h.price}
              style={{
                position: 'relative',
                fontFamily: UI,
                fontWeight: 800,
                fontSize: 52,
                color: C.ink,
                transform: `scale(${s})`
              }}
            >
              RM{h.price}
              <div
                style={{
                  position: 'absolute',
                  left: -6,
                  top: '52%',
                  height: 8,
                  width: `calc(${strike * 100}% + ${strike * 12}px)`,
                  background: C.red,
                  transform: 'rotate(-8deg)'
                }}
              />
            </div>
          )
        })}
      </div>
    </AbsoluteFill>
  )
}
